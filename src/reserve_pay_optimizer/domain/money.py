"""Exact INR money represented as integer paise."""

from dataclasses import InitVar, dataclass
from decimal import Decimal, InvalidOperation

from reserve_pay_optimizer.config import MAX_AMOUNT_PAISE, SUPPORTED_CURRENCY
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.types import Currency


@dataclass(frozen=True, slots=True)
class Money:
    amount_paise: int
    currency: Currency = SUPPORTED_CURRENCY
    _allow_zero: InitVar[bool] = False

    def __post_init__(self, _allow_zero: bool) -> None:
        issues: list[ValidationIssue] = []
        if isinstance(self.amount_paise, bool) or not isinstance(self.amount_paise, int):
            issues.append(
                ValidationIssue(
                    field="amount_paise",
                    code="invalid_type",
                    message="Amount must be an integer number of paise.",
                )
            )
        else:
            if self.amount_paise < 0 or (self.amount_paise == 0 and not _allow_zero):
                issues.append(
                    ValidationIssue(
                        field="amount_paise",
                        code=("must_be_non_negative" if _allow_zero else "must_be_positive"),
                        message=(
                            "Amount must be greater than or equal to zero paise."
                            if _allow_zero
                            else "Amount must be greater than zero paise."
                        ),
                    )
                )
            if self.amount_paise > MAX_AMOUNT_PAISE:
                issues.append(
                    ValidationIssue(
                        field="amount_paise",
                        code="out_of_range",
                        message=f"Amount must not exceed {MAX_AMOUNT_PAISE} paise.",
                    )
                )
        if self.currency is not SUPPORTED_CURRENCY:
            issues.append(
                ValidationIssue(
                    field="currency",
                    code="unsupported_currency",
                    message="Phase 1 supports INR only.",
                )
            )
        if issues:
            raise DomainValidationError(issues)

    @classmethod
    def from_rupees(cls, amount_rupees: Decimal) -> "Money":
        """Create exact money from a Decimal rupee value with at most 2 decimals."""

        if not isinstance(amount_rupees, Decimal):
            raise DomainValidationError(
                [
                    ValidationIssue(
                        field="amount_rupees",
                        code="invalid_type",
                        message="Rupee amounts must be provided as Decimal values.",
                    )
                ]
            )
        try:
            paise = amount_rupees * Decimal(100)
        except InvalidOperation as exc:
            raise DomainValidationError(
                [
                    ValidationIssue(
                        field="amount_rupees",
                        code="invalid_number",
                        message="Rupee amount must be a finite decimal number.",
                    )
                ]
            ) from exc
        if not paise.is_finite():
            raise DomainValidationError(
                [
                    ValidationIssue(
                        field="amount_rupees",
                        code="invalid_number",
                        message="Rupee amount must be a finite decimal number.",
                    )
                ]
            )
        if paise != paise.to_integral_value():
            raise DomainValidationError(
                [
                    ValidationIssue(
                        field="amount_rupees",
                        code="invalid_precision",
                        message="INR amounts may have no more than two decimal places.",
                    )
                ]
            )
        try:
            return cls(amount_paise=int(paise))
        except DomainValidationError as exc:
            raise DomainValidationError(
                [issue.for_field("amount_rupees") for issue in exc.issues]
            ) from exc

    @classmethod
    def from_non_negative_paise(cls, amount_paise: int) -> "Money":
        """Create a Money value for evaluation deltas, where zero is valid."""

        return cls(amount_paise=amount_paise, _allow_zero=True)

    @property
    def amount_rupees(self) -> Decimal:
        return Decimal(self.amount_paise) / Decimal(100)

    def to_dict(self) -> dict[str, object]:
        return {
            "amount_paise": self.amount_paise,
            "currency": self.currency.value,
        }
