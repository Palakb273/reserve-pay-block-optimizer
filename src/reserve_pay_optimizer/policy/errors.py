"""Structured policy feasibility errors."""

from dataclasses import dataclass
from decimal import Decimal

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.policy.risk import RiskProfile


@dataclass(frozen=True, slots=True)
class PolicyTargetNotReachable(ValueError):
    requested_target: Decimal
    maximum_modeled_probability: Decimal
    highest_candidate_probability: Decimal
    profile: RiskProfile

    def __str__(self) -> str:
        return (
            f"{self.profile.value} target {self.requested_target} is not reachable; "
            f"model support is {self.maximum_modeled_probability} and the highest "
            f"candidate probability is {self.highest_candidate_probability}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "error",
            "code": "policy_target_not_reachable",
            "message": str(self),
            "risk_profile": self.profile.value,
            "requested_target": format_ratio(self.requested_target),
            "maximum_modeled_probability": format_ratio(self.maximum_modeled_probability),
            "highest_candidate_probability": format_ratio(self.highest_candidate_probability),
        }
