"""Central immutable merchant risk-profile definitions."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue

MAXIMUM_MODELED_PROBABILITY = Decimal("0.99")


class RiskProfile(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


PROFILE_TARGETS: Mapping[RiskProfile, Decimal] = MappingProxyType(
    {
        RiskProfile.CONSERVATIVE: Decimal("0.99"),
        RiskProfile.BALANCED: Decimal("0.97"),
        RiskProfile.AGGRESSIVE: Decimal("0.93"),
    }
)
DEFAULT_RISK_PROFILE = RiskProfile.BALANCED


@dataclass(frozen=True, slots=True)
class ReserveRiskPolicy:
    profile: RiskProfile
    target_collection_probability: Decimal

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        if not isinstance(self.profile, RiskProfile):
            issues.append(
                ValidationIssue("profile", "invalid_type", "profile must be a RiskProfile.")
            )
        target = self.target_collection_probability
        if not isinstance(target, Decimal) or not target.is_finite():
            issues.append(
                ValidationIssue(
                    "target_collection_probability",
                    "invalid_number",
                    "target_collection_probability must be a finite Decimal.",
                )
            )
        elif target <= 0 or target > MAXIMUM_MODELED_PROBABILITY:
            issues.append(
                ValidationIssue(
                    "target_collection_probability",
                    "unsupported_probability",
                    f"target_collection_probability must be greater than 0 and at most {MAXIMUM_MODELED_PROBABILITY}.",
                )
            )
        elif isinstance(self.profile, RiskProfile) and target != PROFILE_TARGETS[self.profile]:
            issues.append(
                ValidationIssue(
                    "target_collection_probability",
                    "profile_target_mismatch",
                    f"{self.profile.value} requires target {PROFILE_TARGETS[self.profile]}.",
                )
            )
        if issues:
            raise DomainValidationError(issues)

    @classmethod
    def for_profile(cls, profile: RiskProfile | str) -> "ReserveRiskPolicy":
        try:
            normalized = profile if isinstance(profile, RiskProfile) else RiskProfile(profile)
        except ValueError as exc:
            raise DomainValidationError(
                [ValidationIssue("profile", "unsupported_profile", f"Unsupported risk profile: {profile}.")]
            ) from exc
        return cls(normalized, PROFILE_TARGETS[normalized])

    @classmethod
    def default(cls) -> "ReserveRiskPolicy":
        return cls.for_profile(DEFAULT_RISK_PROFILE)

    def to_dict(self) -> dict[str, str]:
        return {
            "risk_profile": self.profile.value,
            "target_collection_probability": str(self.target_collection_probability),
        }


def built_in_policies() -> tuple[ReserveRiskPolicy, ...]:
    return tuple(
        ReserveRiskPolicy.for_profile(profile)
        for profile in (RiskProfile.AGGRESSIVE, RiskProfile.BALANCED, RiskProfile.CONSERVATIVE)
    )
