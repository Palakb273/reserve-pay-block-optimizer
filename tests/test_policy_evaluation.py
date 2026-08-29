from decimal import Decimal, ROUND_CEILING
import unittest

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.risk import RiskProfile
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction
from reserve_pay_optimizer.services.policy_evaluation import evaluate_risk_profiles
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class _DeterministicPredictor:
    """Decision-time-only fixture with a stable distribution around each estimate."""

    ratios = (
        Decimal("0.80"),
        Decimal("0.85"),
        Decimal("0.90"),
        Decimal("1.00"),
        Decimal("1.05"),
        Decimal("1.10"),
        Decimal("1.12"),
        Decimal("1.15"),
        Decimal("1.20"),
        Decimal("1.30"),
    )

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, context):
        self.calls += 1
        amounts = tuple(
            (
                quantile,
                Money(
                    amount_paise=int(
                        (Decimal(context.estimated_amount.amount_paise) * ratio).to_integral_value(
                            rounding=ROUND_CEILING
                        )
                    )
                ),
            )
            for quantile, ratio in zip(QUANTILES, self.ratios, strict=True)
        )
        return FareDistributionPrediction(
            transaction_id=context.transaction_id,
            model_version="deterministic_policy_fixture",
            quantiles=amounts,
        )


class PolicyEvaluationTests(unittest.TestCase):
    def test_profiles_and_baselines_share_one_evaluation_path_and_predictions(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(transaction_count=49, seed=606, customer_pool_size=12)
        )
        predictor = _DeterministicPredictor()
        evaluation = evaluate_risk_profiles(
            dataset.transactions,
            dataset.outcomes,
            predictor,
            ReserveBlockOptimizer(
                OptimizationConfig(
                    lambda_under=Decimal("0.1"),
                    lambda_excess=Decimal("1"),
                    lambda_friction=Decimal("1"),
                    candidate_step_paise=500,
                )
            ),
        )

        self.assertEqual(predictor.calls, len(dataset.records))
        strategies = {metrics.strategy for metrics in evaluation.comparison.metrics}
        self.assertEqual(
            strategies,
            {
                "exact_estimate",
                "fixed_buffer_20",
                "optimized_aggressive",
                "optimized_balanced",
                "optimized_conservative",
            },
        )
        diagnostics = dict(evaluation.profile_diagnostics)
        self.assertEqual(set(diagnostics), set(RiskProfile))
        for profile, item in diagnostics.items():
            self.assertEqual(item.policy.profile, profile)
            self.assertEqual(item.policy_satisfaction_rate, Decimal(1))
            self.assertGreaterEqual(
                item.average_estimated_collection_probability,
                item.policy.target_collection_probability,
            )
            self.assertEqual(sum(city.record_count for city in item.per_city), 49)
            self.assertTrue(all(city.profile is profile for city in item.per_city))

    def test_estimated_policy_satisfaction_is_separate_from_realized_success(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(transaction_count=21, seed=607, customer_pool_size=7)
        )
        evaluation = evaluate_risk_profiles(
            dataset.transactions,
            dataset.outcomes,
            _DeterministicPredictor(),
        )
        for _, diagnostics in evaluation.profile_diagnostics:
            self.assertEqual(diagnostics.policy_satisfaction_rate, Decimal(1))
            self.assertEqual(
                diagnostics.policy_calibration_difference,
                diagnostics.realized_collection_success
                - diagnostics.policy.target_collection_probability,
            )


if __name__ == "__main__":
    unittest.main()
