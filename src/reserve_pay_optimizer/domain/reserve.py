"""Reserve strategy output contracts."""

from dataclasses import dataclass

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.money import Money


@dataclass(frozen=True, slots=True)
class ReserveDecision:
    """A deterministic block decision made from decision-time context only."""

    transaction_id: str
    strategy: str
    strategy_version: str
    block_amount: Money
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        for field, value in (
            ("transaction_id", self.transaction_id),
            ("strategy", self.strategy),
            ("strategy_version", self.strategy_version),
        ):
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    ValidationIssue(field, "required", f"{field} cannot be empty.")
                )
        if not isinstance(self.block_amount, Money):
            issues.append(
                ValidationIssue(
                    "block_amount_paise",
                    "invalid_type",
                    "block_amount must be Money.",
                )
            )
        if not isinstance(self.parameters, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not all(isinstance(value, str) for value in item)
            for item in self.parameters
        ):
            issues.append(
                ValidationIssue(
                    "parameters",
                    "invalid_type",
                    "parameters must be string key/value pairs.",
                )
            )
        if issues:
            raise DomainValidationError(issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "strategy": self.strategy,
            "strategy_version": self.strategy_version,
            "block_amount_paise": self.block_amount.amount_paise,
            "parameters": dict(self.parameters),
        }

