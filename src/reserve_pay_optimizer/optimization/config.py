"""Validated low-level optimization parameters without named risk profiles."""

from dataclasses import dataclass
from decimal import Decimal

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue


@dataclass(frozen=True, slots=True)
class OptimizationConfig:
    """Project policy parameters, not Razorpay production risk coefficients."""

    lambda_under: Decimal = Decimal("4.0")
    lambda_excess: Decimal = Decimal("1.0")
    lambda_friction: Decimal = Decimal("0.5")
    candidate_step_paise: int = 100

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        for field in ("lambda_under", "lambda_excess", "lambda_friction"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                issues.append(
                    ValidationIssue(field, "invalid_type", f"{field} must be an int or Decimal, not float.")
                )
                continue
            normalized = Decimal(value)
            if not normalized.is_finite():
                issues.append(
                    ValidationIssue(field, "invalid_number", f"{field} must be finite.")
                )
            elif normalized < 0:
                issues.append(
                    ValidationIssue(field, "must_be_non_negative", f"{field} must be non-negative.")
                )
            else:
                object.__setattr__(self, field, normalized)
        if not issues and self.lambda_under == self.lambda_excess == self.lambda_friction == 0:
            issues.append(
                ValidationIssue("objective_weights", "all_zero", "At least one objective weight must be positive.")
            )
        if isinstance(self.candidate_step_paise, bool) or not isinstance(self.candidate_step_paise, int):
            issues.append(
                ValidationIssue("candidate_step_paise", "invalid_type", "candidate_step_paise must be an integer.")
            )
        elif self.candidate_step_paise <= 0:
            issues.append(
                ValidationIssue("candidate_step_paise", "must_be_positive", "candidate_step_paise must be positive.")
            )
        if issues:
            raise DomainValidationError(issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "lambda_under": str(self.lambda_under),
            "lambda_excess": str(self.lambda_excess),
            "lambda_friction": str(self.lambda_friction),
            "candidate_step_paise": self.candidate_step_paise,
        }
