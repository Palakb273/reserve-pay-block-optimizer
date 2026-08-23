"""Configurable exact-arithmetic fixed-buffer reserve baseline."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from reserve_pay_optimizer.config import DEFAULT_FIXED_BUFFER_PERCENTAGE
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision


def _percentage_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True, slots=True)
class FixedBufferStrategy:
    """Block the estimate plus a fixed percentage, rounded up to one paise."""

    buffer_percentage: Decimal = DEFAULT_FIXED_BUFFER_PERCENTAGE

    def __post_init__(self) -> None:
        value = self.buffer_percentage
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise DomainValidationError(
                [
                    ValidationIssue(
                        "buffer_percentage",
                        "invalid_type",
                        "buffer_percentage must be an int or Decimal, not float.",
                    )
                ]
            )
        normalized = Decimal(value)
        if not normalized.is_finite():
            raise DomainValidationError(
                [
                    ValidationIssue(
                        "buffer_percentage",
                        "invalid_number",
                        "buffer_percentage must be finite.",
                    )
                ]
            )
        if normalized < 0:
            raise DomainValidationError(
                [
                    ValidationIssue(
                        "buffer_percentage",
                        "must_be_non_negative",
                        "buffer_percentage must be greater than or equal to zero.",
                    )
                ]
            )
        object.__setattr__(self, "buffer_percentage", normalized)

    @property
    def strategy_id(self) -> str:
        percentage = _percentage_text(self.buffer_percentage).replace(".", "_")
        return f"fixed_buffer_{percentage}"

    def calculate_block(
        self, transaction: RideTransactionContext
    ) -> ReserveDecision:
        multiplier = Decimal(1) + (self.buffer_percentage / Decimal(100))
        unrounded_paise = Decimal(
            transaction.estimated_amount.amount_paise
        ) * multiplier
        block_paise = int(unrounded_paise.to_integral_value(rounding=ROUND_CEILING))
        try:
            block_amount = Money(amount_paise=block_paise)
        except DomainValidationError as exc:
            raise DomainValidationError(
                [issue.for_field("block_amount_paise") for issue in exc.issues]
            ) from exc
        return ReserveDecision(
            transaction_id=transaction.transaction_id,
            strategy=self.strategy_id,
            strategy_version="1",
            block_amount=block_amount,
            parameters=(("buffer_percentage", _percentage_text(self.buffer_percentage)),),
        )
