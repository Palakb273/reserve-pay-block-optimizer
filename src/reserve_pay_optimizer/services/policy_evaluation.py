"""Evaluate all merchant policies through the existing retrospective metrics."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from reserve_pay_optimizer.domain.evaluation import BaselineComparison, StrategyMetrics, format_ratio
from reserve_pay_optimizer.domain.mobility import RideTransactionContext, RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.models import PolicyOptimizationResult
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile, built_in_policies
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.evaluation import aggregate_evaluations, evaluate_transaction
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from reserve_pay_optimizer.strategies.optimized import FareDistributionPredictor, OptimizedReserveStrategy


def _average_paise(values: Sequence[int]) -> Money:
    rounded = int(
        (Decimal(sum(values)) / Decimal(len(values))).to_integral_value(rounding=ROUND_HALF_UP)
    )
    return Money.from_non_negative_paise(rounded)


class _CachingPredictor:
    def __init__(self, predictor: FareDistributionPredictor) -> None:
        self.predictor = predictor
        self.cache = {}

    def predict(self, context: RideTransactionContext):
        if context.transaction_id not in self.cache:
            self.cache[context.transaction_id] = self.predictor.predict(context)
        return self.cache[context.transaction_id]


@dataclass(frozen=True, slots=True)
class CityPolicyDiagnostics:
    city: str
    record_count: int
    profile: RiskProfile
    target_probability: Decimal
    realized_collection_success: Decimal
    average_block: Money
    average_excess: Money

    def to_dict(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "profile": self.profile.value,
            "target_collection_probability": format_ratio(self.target_probability),
            "realized_collection_success": format_ratio(self.realized_collection_success),
            "average_block_paise": self.average_block.amount_paise,
            "average_excess_block_paise": self.average_excess.amount_paise,
        }


@dataclass(frozen=True, slots=True)
class ProfilePolicyDiagnostics:
    policy: ReserveRiskPolicy
    average_estimated_collection_probability: Decimal
    policy_satisfaction_rate: Decimal
    average_recommended_block: Money
    average_expected_excess: Money
    average_objective_score: Decimal
    realized_collection_success: Decimal
    policy_calibration_difference: Decimal
    per_city: tuple[CityPolicyDiagnostics, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "target_collection_probability": format_ratio(
                self.policy.target_collection_probability
            ),
            "average_estimated_collection_probability": format_ratio(
                self.average_estimated_collection_probability
            ),
            "policy_satisfaction_rate": format_ratio(self.policy_satisfaction_rate),
            "average_recommended_block_paise": self.average_recommended_block.amount_paise,
            "average_expected_excess_block_paise": self.average_expected_excess.amount_paise,
            "average_objective_score": format_ratio(self.average_objective_score),
            "realized_collection_success": format_ratio(self.realized_collection_success),
            "policy_calibration_difference": format_ratio(
                self.policy_calibration_difference
            ),
            "per_city": {item.city: item.to_dict() for item in self.per_city},
        }


@dataclass(frozen=True, slots=True)
class RiskProfileEvaluation:
    comparison: BaselineComparison
    optimizer_config: OptimizationConfig
    profile_diagnostics: tuple[tuple[RiskProfile, ProfilePolicyDiagnostics], ...]

    def to_dict(self) -> dict[str, object]:
        value = self.comparison.to_dict()
        value.update(
            {
                "optimizer_configuration": self.optimizer_config.to_dict(),
                "risk_profile_diagnostics": {
                    profile.value: diagnostics.to_dict()
                    for profile, diagnostics in self.profile_diagnostics
                },
            }
        )
        return value


def _city_diagnostics(
    transactions: Sequence[RideTransactionContext],
    outcomes_by_id: dict[str, RideTransactionOutcome],
    results_by_id: dict[str, PolicyOptimizationResult],
    policy: ReserveRiskPolicy,
) -> tuple[CityPolicyDiagnostics, ...]:
    diagnostics = []
    for city in sorted({transaction.city for transaction in transactions}, key=lambda item: item.value):
        city_transactions = [transaction for transaction in transactions if transaction.city is city]
        evaluations = [
            evaluate_transaction(
                transaction,
                results_by_id[transaction.transaction_id].reserve_decision,
                outcomes_by_id[transaction.transaction_id],
            )
            for transaction in city_transactions
        ]
        metrics = aggregate_evaluations(evaluations)
        diagnostics.append(
            CityPolicyDiagnostics(
                city=city.value,
                record_count=len(city_transactions),
                profile=policy.profile,
                target_probability=policy.target_collection_probability,
                realized_collection_success=metrics.collection_success_rate,
                average_block=_average_paise(
                    [evaluation.block_amount.amount_paise for evaluation in evaluations]
                ),
                average_excess=metrics.average_excess_block,
            )
        )
    return tuple(diagnostics)


def evaluate_risk_profiles(
    transactions: Sequence[RideTransactionContext],
    outcomes: Sequence[RideTransactionOutcome],
    predictor: FareDistributionPredictor,
    optimizer: ReserveBlockOptimizer | None = None,
) -> RiskProfileEvaluation:
    resolved_optimizer = optimizer or ReserveBlockOptimizer()
    caching_predictor = _CachingPredictor(predictor)
    policies = built_in_policies()
    policy_strategies = tuple(
        OptimizedReserveStrategy(caching_predictor, resolved_optimizer, policy)
        for policy in policies
    )
    comparison = compare_strategies(
        transactions,
        outcomes,
        (ExactEstimateStrategy(), FixedBufferStrategy(), *policy_strategies),
    )
    metrics_by_strategy: dict[str, StrategyMetrics] = {
        metrics.strategy: metrics for metrics in comparison.metrics
    }
    outcomes_by_id = {outcome.transaction_id: outcome for outcome in outcomes}
    profile_diagnostics = []
    for policy, strategy in zip(policies, policy_strategies, strict=True):
        results = tuple(strategy.optimization_results)
        policy_results = tuple(
            result for result in results if isinstance(result, PolicyOptimizationResult)
        )
        if len(policy_results) != len(results) or not policy_results:
            raise ValueError("policy strategy did not produce policy-aware results")
        count = Decimal(len(policy_results))
        metrics = metrics_by_strategy[strategy.strategy_id]
        results_by_id = {result.transaction_id: result for result in policy_results}
        average_estimated = sum(
            (result.estimated_collection_probability for result in policy_results), Decimal(0)
        ) / count
        satisfaction = Decimal(sum(result.policy_satisfied for result in policy_results)) / count
        profile_diagnostics.append(
            (
                policy.profile,
                ProfilePolicyDiagnostics(
                    policy=policy,
                    average_estimated_collection_probability=average_estimated,
                    policy_satisfaction_rate=satisfaction,
                    average_recommended_block=_average_paise(
                        [result.recommended_block.amount_paise for result in policy_results]
                    ),
                    average_expected_excess=_average_paise(
                        [result.expected_excess_block.amount_paise for result in policy_results]
                    ),
                    average_objective_score=sum(
                        (result.objective_score for result in policy_results), Decimal(0)
                    ) / count,
                    realized_collection_success=metrics.collection_success_rate,
                    policy_calibration_difference=(
                        metrics.collection_success_rate - policy.target_collection_probability
                    ),
                    per_city=_city_diagnostics(
                        transactions, outcomes_by_id, results_by_id, policy
                    ),
                ),
            )
        )
    return RiskProfileEvaluation(
        comparison=comparison,
        optimizer_config=resolved_optimizer.config,
        profile_diagnostics=tuple(profile_diagnostics),
    )
