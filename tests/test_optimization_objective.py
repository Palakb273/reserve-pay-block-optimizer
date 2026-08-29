from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.optimization.candidates import generate_candidates
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.distribution import QuantileDistribution
from reserve_pay_optimizer.optimization.objective import score_candidate
from tests.optimization_fixtures import distribution_prediction, optimization_context


class OptimizationConfigTests(unittest.TestCase):
    def test_defaults_are_explicit_low_level_weights(self) -> None:
        self.assertEqual(
            OptimizationConfig().to_dict(),
            {
                "lambda_under": "4.0",
                "lambda_excess": "1.0",
                "lambda_friction": "0.5",
                "candidate_step_paise": 100,
            },
        )

    def test_negative_all_zero_float_and_invalid_step_are_rejected(self) -> None:
        invalid = (
            {"lambda_under": Decimal("-1")},
            {"lambda_under": Decimal(0), "lambda_excess": Decimal(0), "lambda_friction": Decimal(0)},
            {"lambda_under": 1.0},
            {"candidate_step_paise": 0},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(DomainValidationError):
                OptimizationConfig(**values)

    def test_zero_weights_are_valid_when_one_component_remains(self) -> None:
        config = OptimizationConfig(
            lambda_under=Decimal(1), lambda_excess=Decimal(0), lambda_friction=Decimal(0)
        )
        self.assertEqual(config.lambda_under, Decimal(1))


class CandidateAndObjectiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = optimization_context()
        self.prediction = distribution_prediction()

    def test_candidates_are_deterministic_sorted_unique_and_complete(self) -> None:
        config = OptimizationConfig(candidate_step_paise=500)
        first = generate_candidates(self.context, self.prediction, config)
        second = generate_candidates(self.context, self.prediction, config)
        self.assertEqual(first, second)
        self.assertEqual(first, tuple(sorted(set(first))))
        self.assertIn(10000, first)
        for _, amount in self.prediction.quantiles:
            self.assertIn(amount.amount_paise, first)
        self.assertGreater(min(first), 0)
        self.assertEqual(max(first), 18000)

    def test_score_is_exact_weighted_normalized_formula(self) -> None:
        config = OptimizationConfig(
            lambda_under=Decimal(2),
            lambda_excess=Decimal(3),
            lambda_friction=Decimal(4),
        )
        distribution = QuantileDistribution(self.prediction)
        score = score_candidate(self.context, distribution, 12000, config)
        self.assertEqual(score.estimated_collection_probability, Decimal("0.75"))
        self.assertEqual(score.estimated_under_block_probability, Decimal("0.25"))
        self.assertEqual(
            score.expected_excess_block_ratio,
            distribution.expected_excess_paise(12000) / Decimal(10000),
        )
        self.assertEqual(score.friction_ratio, Decimal("0.2"))
        self.assertEqual(score.score_components.under_block_component, Decimal("0.50"))
        self.assertEqual(
            score.objective_score,
            Decimal(2) * score.estimated_under_block_probability
            + Decimal(3) * score.expected_excess_block_ratio
            + Decimal(4) * score.friction_ratio,
        )

    def test_monotonic_score_inputs_as_block_increases(self) -> None:
        distribution = QuantileDistribution(self.prediction)
        scores = [
            score_candidate(self.context, distribution, amount, OptimizationConfig())
            for amount in (8000, 10000, 12000, 15000, 18000)
        ]
        under = [score.estimated_under_block_probability for score in scores]
        excess = [score.expected_excess_block_paise_exact for score in scores]
        friction = [score.friction_ratio for score in scores]
        self.assertEqual(under, sorted(under, reverse=True))
        self.assertEqual(excess, sorted(excess))
        self.assertEqual(friction, sorted(friction))


if __name__ == "__main__":
    unittest.main()
