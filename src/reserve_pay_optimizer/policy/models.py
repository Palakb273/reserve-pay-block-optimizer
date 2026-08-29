"""Policy-aware result layered over the unchanged Phase-5 result."""

from dataclasses import dataclass
from decimal import Decimal

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.optimization.models import OptimizationResult
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy


@dataclass(frozen=True, slots=True)
class PolicyOptimizationResult:
    optimization: OptimizationResult
    risk_policy: ReserveRiskPolicy
    feasible_candidate_count: int

    @property
    def transaction_id(self) -> str:
        return self.optimization.transaction_id

    @property
    def recommended_block(self) -> Money:
        return self.optimization.recommended_block

    @property
    def estimated_collection_probability(self) -> Decimal:
        return self.optimization.estimated_collection_probability

    @property
    def estimated_under_block_probability(self) -> Decimal:
        return self.optimization.estimated_under_block_probability

    @property
    def expected_excess_block(self) -> Money:
        return self.optimization.expected_excess_block

    @property
    def expected_excess_block_ratio(self) -> Decimal:
        return self.optimization.expected_excess_block_ratio

    @property
    def friction_ratio(self) -> Decimal:
        return self.optimization.friction_ratio

    @property
    def objective_score(self) -> Decimal:
        return self.optimization.objective_score

    @property
    def score_components(self):
        return self.optimization.score_components

    @property
    def candidate_count(self) -> int:
        return self.optimization.candidate_count

    @property
    def model_version(self) -> str:
        return self.optimization.model_version

    @property
    def optimization_config(self):
        return self.optimization.optimization_config

    @property
    def policy_satisfied(self) -> bool:
        return (
            self.estimated_collection_probability
            >= self.risk_policy.target_collection_probability
        )

    @property
    def strategy_id(self) -> str:
        return f"optimized_{self.risk_policy.profile.value}"

    @property
    def reserve_decision(self) -> ReserveDecision:
        parameters = tuple(
            (key, str(value)) for key, value in self.optimization_config.to_dict().items()
        ) + (
            ("model_version", self.model_version),
            ("risk_profile", self.risk_policy.profile.value),
            ("target_collection_probability", str(self.risk_policy.target_collection_probability)),
            ("policy_satisfied", str(self.policy_satisfied).lower()),
        )
        return ReserveDecision(
            transaction_id=self.transaction_id,
            strategy=self.strategy_id,
            strategy_version="1",
            block_amount=self.recommended_block,
            parameters=parameters,
        )

    def to_dict(self, *, include_candidates: bool = False) -> dict[str, object]:
        value = self.optimization.to_dict(include_candidates=include_candidates)
        value.update(
            {
                "risk_profile": self.risk_policy.profile.value,
                "target_collection_probability": format_ratio(
                    self.risk_policy.target_collection_probability
                ),
                "policy_satisfied": self.policy_satisfied,
                "feasible_candidate_count": self.feasible_candidate_count,
            }
        )
        return value
