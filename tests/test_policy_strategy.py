from decimal import Decimal
import unittest

from reserve_pay_optimizer.services.evaluation import evaluate_transaction
from reserve_pay_optimizer.strategies.base import ReserveStrategy
from reserve_pay_optimizer.strategies.optimized import OptimizedReserveStrategy
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from tests.fixtures import make_outcome
from tests.optimization_fixtures import distribution_prediction, optimization_context


class FixturePredictor:
    def predict(self, context):
        return distribution_prediction(context.transaction_id)


class PolicyStrategyTests(unittest.TestCase):
    def test_one_strategy_class_exposes_profile_specific_identifier(self) -> None:
        for profile in RiskProfile:
            strategy = OptimizedReserveStrategy(
                FixturePredictor(), risk_policy=ReserveRiskPolicy.for_profile(profile)
            )
            self.assertIsInstance(strategy, ReserveStrategy)
            self.assertEqual(strategy.strategy_id, f"optimized_{profile.value}")
            decision = strategy.calculate_block(optimization_context())
            self.assertEqual(decision.strategy, strategy.strategy_id)
            self.assertEqual(dict(decision.parameters)["risk_profile"], profile.value)

    def test_policy_satisfaction_is_not_realized_collection_success(self) -> None:
        context = optimization_context()
        strategy = OptimizedReserveStrategy(
            FixturePredictor(),
            risk_policy=ReserveRiskPolicy.for_profile(RiskProfile.BALANCED),
        )
        decision = strategy.calculate_block(context)
        result = strategy.optimization_results[0]
        self.assertTrue(result.policy_satisfied)  # type: ignore[union-attr]
        retrospective = evaluate_transaction(
            context,
            decision,
            make_outcome(context.transaction_id, decision.block_amount.amount_paise + 1),
        )
        self.assertFalse(retrospective.collection_success)

    def test_customer_identity_does_not_change_controlled_policy_decision(self) -> None:
        first = optimization_context("A")
        second = optimization_context("B")
        strategy = OptimizedReserveStrategy(
            FixturePredictor(),
            risk_policy=ReserveRiskPolicy.for_profile(RiskProfile.BALANCED),
        )
        self.assertEqual(
            strategy.calculate_block(first).block_amount.amount_paise,
            strategy.calculate_block(second).block_amount.amount_paise,
        )


if __name__ == "__main__":
    unittest.main()
