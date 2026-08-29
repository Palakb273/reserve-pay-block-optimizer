from decimal import Decimal
from inspect import signature
import unittest

from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.errors import PolicyTargetNotReachable
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile, built_in_policies
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction
from tests.fixtures import make_outcome
from tests.optimization_fixtures import distribution_prediction, optimization_context


class PolicyOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = optimization_context()
        self.prediction = distribution_prediction()
        self.phase5 = ReserveBlockOptimizer(
            OptimizationConfig(
                lambda_under=Decimal("0.1"),
                lambda_excess=Decimal(1),
                lambda_friction=Decimal(1),
                candidate_step_paise=500,
            )
        )
        self.optimizer = PolicyConstrainedOptimizer(self.phase5)

    def test_only_feasible_candidates_are_eligible_and_true_minimum_wins(self) -> None:
        policy = ReserveRiskPolicy.for_profile(RiskProfile.BALANCED)
        result = self.optimizer.optimize(self.context, self.prediction, policy)
        all_scores = self.phase5.score_candidates(self.context, self.prediction)
        feasible = tuple(
            score for score in all_scores
            if score.estimated_collection_probability >= Decimal("0.97")
        )
        self.assertEqual(result.feasible_candidate_count, len(feasible))
        self.assertEqual(result.objective_score, min(score.objective_score for score in feasible))
        self.assertGreaterEqual(result.estimated_collection_probability, Decimal("0.97"))
        self.assertTrue(result.policy_satisfied)

    def test_profile_block_and_probability_ordering(self) -> None:
        results = {
            policy.profile: self.optimizer.optimize(self.context, self.prediction, policy)
            for policy in built_in_policies()
        }
        aggressive = results[RiskProfile.AGGRESSIVE]
        balanced = results[RiskProfile.BALANCED]
        conservative = results[RiskProfile.CONSERVATIVE]
        self.assertGreaterEqual(conservative.recommended_block.amount_paise, balanced.recommended_block.amount_paise)
        self.assertGreaterEqual(balanced.recommended_block.amount_paise, aggressive.recommended_block.amount_paise)
        self.assertEqual(aggressive.recommended_block.amount_paise, 14500)
        self.assertEqual(balanced.recommended_block.amount_paise, 16000)
        self.assertEqual(conservative.recommended_block.amount_paise, 18000)
        for profile, result in results.items():
            self.assertGreaterEqual(
                result.estimated_collection_probability,
                ReserveRiskPolicy.for_profile(profile).target_collection_probability,
            )

    def test_all_profiles_reuse_exactly_the_same_objective_config(self) -> None:
        results = [
            self.optimizer.optimize(self.context, self.prediction, policy)
            for policy in built_in_policies()
        ]
        self.assertTrue(all(result.optimization_config == self.phase5.config for result in results))

    def test_policy_result_and_optimizer_accept_no_outcome(self) -> None:
        result = self.optimizer.optimize(
            self.context,
            self.prediction,
            ReserveRiskPolicy.for_profile(RiskProfile.BALANCED),
        )
        serialized = result.to_dict()
        self.assertNotIn("actual_amount", serialized)
        self.assertNotIn("completed_at", serialized)
        self.assertEqual(
            tuple(signature(PolicyConstrainedOptimizer.optimize).parameters),
            ("self", "transaction", "prediction", "policy"),
        )
        with self.assertRaises(TypeError):
            self.optimizer.optimize(  # type: ignore[call-arg]
                self.context, self.prediction,
                ReserveRiskPolicy.for_profile(RiskProfile.BALANCED), make_outcome()
            )

    def test_unsupported_model_support_raises_structured_error(self) -> None:
        partial_prediction = FareDistributionPrediction(
            transaction_id=self.context.transaction_id,
            model_version="partial",
            quantiles=self.prediction.quantiles[:-1],
        )
        with self.assertRaises(PolicyTargetNotReachable) as caught:
            self.optimizer.optimize(
                self.context,
                partial_prediction,
                ReserveRiskPolicy.for_profile(RiskProfile.CONSERVATIVE),
            )
        error = caught.exception.to_dict()
        self.assertEqual(error["code"], "policy_target_not_reachable")
        self.assertEqual(error["requested_target"], "0.990000")
        self.assertEqual(error["maximum_modeled_probability"], "0.970000")


if __name__ == "__main__":
    unittest.main()
