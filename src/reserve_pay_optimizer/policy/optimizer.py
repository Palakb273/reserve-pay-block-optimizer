"""Policy feasibility constraint layered over Phase-5 candidate scoring."""

from decimal import Decimal

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.optimization.distribution import QuantileDistribution
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.errors import PolicyTargetNotReachable
from reserve_pay_optimizer.policy.models import PolicyOptimizationResult
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


class PolicyConstrainedOptimizer:
    def __init__(self, optimizer: ReserveBlockOptimizer | None = None) -> None:
        self.optimizer = optimizer or ReserveBlockOptimizer()

    def optimize(
        self,
        transaction: RideTransactionContext,
        prediction: FareDistributionPrediction,
        policy: ReserveRiskPolicy,
    ) -> PolicyOptimizationResult:
        maximum_modeled = QuantileDistribution(prediction).highest_modeled_probability
        if policy.target_collection_probability > maximum_modeled:
            raise PolicyTargetNotReachable(
                requested_target=policy.target_collection_probability,
                maximum_modeled_probability=maximum_modeled,
                highest_candidate_probability=maximum_modeled,
                profile=policy.profile,
            )
        scores = self.optimizer.score_candidates(transaction, prediction)
        highest_candidate = max(
            (score.estimated_collection_probability for score in scores), default=Decimal(0)
        )
        feasible = tuple(
            score
            for score in scores
            if score.estimated_collection_probability >= policy.target_collection_probability
        )
        if not feasible:
            raise PolicyTargetNotReachable(
                requested_target=policy.target_collection_probability,
                maximum_modeled_probability=maximum_modeled,
                highest_candidate_probability=highest_candidate,
                profile=policy.profile,
            )
        optimization = self.optimizer.build_result(
            transaction,
            prediction,
            feasible,
            candidate_count=len(scores),
        )
        return PolicyOptimizationResult(
            optimization=optimization,
            risk_policy=policy,
            feasible_candidate_count=len(feasible),
        )
