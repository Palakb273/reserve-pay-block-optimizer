from decimal import Decimal
from inspect import signature
import unittest

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.optimization.candidates import generate_candidates
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.distribution import QuantileDistribution
from reserve_pay_optimizer.optimization.objective import score_candidate
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from tests.fixtures import make_outcome
from tests.optimization_fixtures import distribution_prediction, optimization_context


class ReserveBlockOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = optimization_context()
        self.prediction = distribution_prediction()

    def test_selected_candidate_is_the_true_minimum(self) -> None:
        optimizer = ReserveBlockOptimizer()
        result = optimizer.optimize(self.context, self.prediction)
        candidates = generate_candidates(self.context, self.prediction, optimizer.config)
        scores = [
            score_candidate(self.context, QuantileDistribution(self.prediction), value, optimizer.config)
            for value in candidates
        ]
        self.assertLessEqual(result.objective_score, min(score.objective_score for score in scores))
        self.assertTrue(all(result.objective_score <= score.objective_score for score in scores))
        self.assertIsInstance(result.recommended_block, Money)

    def test_tie_break_chooses_smaller_block(self) -> None:
        optimizer = ReserveBlockOptimizer(
            OptimizationConfig(
                lambda_under=Decimal(0), lambda_excess=Decimal(0), lambda_friction=Decimal(1)
            )
        )
        result = optimizer.optimize(self.context, self.prediction)
        self.assertEqual(result.recommended_block.amount_paise, 5000)

    def test_weight_extremes_move_selection_in_expected_direction(self) -> None:
        low_under = ReserveBlockOptimizer(
            OptimizationConfig(lambda_under=Decimal("0.1"), lambda_excess=Decimal(1), lambda_friction=Decimal(1))
        ).optimize(self.context, self.prediction)
        high_under = ReserveBlockOptimizer(
            OptimizationConfig(lambda_under=Decimal(20), lambda_excess=Decimal(1), lambda_friction=Decimal(1))
        ).optimize(self.context, self.prediction)
        self.assertGreaterEqual(high_under.recommended_block.amount_paise, low_under.recommended_block.amount_paise)

        low_cost = ReserveBlockOptimizer(
            OptimizationConfig(lambda_under=Decimal(2), lambda_excess=Decimal("0.1"), lambda_friction=Decimal("0.1"))
        ).optimize(self.context, self.prediction)
        high_cost = ReserveBlockOptimizer(
            OptimizationConfig(lambda_under=Decimal(2), lambda_excess=Decimal(10), lambda_friction=Decimal(10))
        ).optimize(self.context, self.prediction)
        self.assertLessEqual(high_cost.recommended_block.amount_paise, low_cost.recommended_block.amount_paise)

    def test_result_contains_no_outcome_information(self) -> None:
        result = ReserveBlockOptimizer().optimize(self.context, self.prediction)
        serialized = result.to_dict()
        self.assertNotIn("actual_amount", serialized)
        self.assertNotIn("actual_amount_paise", serialized)
        self.assertNotIn("completed_at", serialized)
        self.assertEqual(
            tuple(signature(ReserveBlockOptimizer.optimize).parameters),
            ("self", "transaction", "prediction"),
        )
        with self.assertRaises(TypeError):
            ReserveBlockOptimizer().optimize(self.context, self.prediction, make_outcome())  # type: ignore[call-arg]

    def test_mismatched_prediction_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReserveBlockOptimizer().optimize(self.context, distribution_prediction("OTHER"))


if __name__ == "__main__":
    unittest.main()
