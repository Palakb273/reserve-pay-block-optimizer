"""India-first mobility transaction contracts.

The context contains decision-time inputs only. The outcome is deliberately a
separate model so an actual fare cannot leak into future prediction features.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from reserve_pay_optimizer.config import (
    INDIA_STANDARD_TIME,
    MOBILITY_DOMAIN,
    SUPPORTED_CURRENCY,
)
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import Currency, SupportedCity, TransactionDomain


def _validate_identifier(value: object, field: str) -> list[ValidationIssue]:
    if not isinstance(value, str):
        return [ValidationIssue(field, "invalid_type", f"{field} must be a string.")]
    if not value.strip():
        return [ValidationIssue(field, "required", f"{field} cannot be empty.")]
    return []


def _validate_aware_timestamp(value: object, field: str) -> list[ValidationIssue]:
    if not isinstance(value, datetime):
        return [
            ValidationIssue(field, "invalid_type", f"{field} must be a datetime value.")
        ]
    if value.tzinfo is None or value.utcoffset() is None:
        return [
            ValidationIssue(
                field,
                "timezone_required",
                f"{field} must include a UTC offset.",
            )
        ]
    return []


@dataclass(frozen=True, slots=True)
class RideTransactionContext:
    """Information available when an initial ride reserve decision is made."""

    transaction_id: str
    customer_id: str
    estimated_amount: Money
    city: SupportedCity
    distance_km: Decimal
    estimated_duration_minutes: int
    surge_multiplier: Decimal
    timestamp: datetime

    domain: ClassVar[TransactionDomain] = MOBILITY_DOMAIN
    currency: ClassVar[Currency] = SUPPORTED_CURRENCY

    def __post_init__(self) -> None:
        issues = _validate_identifier(self.transaction_id, "transaction_id")
        issues.extend(_validate_identifier(self.customer_id, "customer_id"))
        if not isinstance(self.estimated_amount, Money):
            issues.append(
                ValidationIssue(
                    "estimated_amount_paise",
                    "invalid_type",
                    "estimated_amount must be Money.",
                )
            )
        if not isinstance(self.city, SupportedCity):
            issues.append(
                ValidationIssue("city", "unsupported_city", "City is not supported.")
            )
        if not isinstance(self.distance_km, Decimal) or not self.distance_km.is_finite():
            issues.append(
                ValidationIssue(
                    "distance_km",
                    "invalid_number",
                    "distance_km must be a finite decimal number.",
                )
            )
        elif self.distance_km < 0:
            issues.append(
                ValidationIssue(
                    "distance_km",
                    "must_be_non_negative",
                    "distance_km must be greater than or equal to zero.",
                )
            )
        if (
            isinstance(self.estimated_duration_minutes, bool)
            or not isinstance(self.estimated_duration_minutes, int)
        ):
            issues.append(
                ValidationIssue(
                    "estimated_duration_minutes",
                    "invalid_type",
                    "estimated_duration_minutes must be an integer.",
                )
            )
        elif self.estimated_duration_minutes < 0:
            issues.append(
                ValidationIssue(
                    "estimated_duration_minutes",
                    "must_be_non_negative",
                    "estimated_duration_minutes must be greater than or equal to zero.",
                )
            )
        if (
            not isinstance(self.surge_multiplier, Decimal)
            or not self.surge_multiplier.is_finite()
        ):
            issues.append(
                ValidationIssue(
                    "surge_multiplier",
                    "invalid_number",
                    "surge_multiplier must be a finite decimal number.",
                )
            )
        elif self.surge_multiplier <= 0:
            issues.append(
                ValidationIssue(
                    "surge_multiplier",
                    "must_be_positive",
                    "surge_multiplier must be greater than zero.",
                )
            )
        issues.extend(_validate_aware_timestamp(self.timestamp, "timestamp"))
        if issues:
            raise DomainValidationError(issues)

    @property
    def day_of_week(self) -> str:
        return self.timestamp.astimezone(INDIA_STANDARD_TIME).strftime("%A").lower()

    def to_dict(self) -> dict[str, object]:
        india_timestamp = self.timestamp.astimezone(INDIA_STANDARD_TIME)
        return {
            "transaction_id": self.transaction_id,
            "customer_id": self.customer_id,
            "estimated_amount_paise": self.estimated_amount.amount_paise,
            "currency": self.currency.value,
            "domain": self.domain.value,
            "city": self.city.value,
            "distance_km": float(self.distance_km),
            "estimated_duration_minutes": self.estimated_duration_minutes,
            "surge_multiplier": float(self.surge_multiplier),
            "timestamp": india_timestamp.isoformat(),
            "day_of_week": self.day_of_week,
        }


@dataclass(frozen=True, slots=True)
class RideTransactionOutcome:
    """Post-ride facts that are unavailable to the initial decision engine."""

    transaction_id: str
    actual_amount: Money
    completed_at: datetime

    domain: ClassVar[TransactionDomain] = MOBILITY_DOMAIN
    currency: ClassVar[Currency] = SUPPORTED_CURRENCY

    def __post_init__(self) -> None:
        issues = _validate_identifier(self.transaction_id, "transaction_id")
        if not isinstance(self.actual_amount, Money):
            issues.append(
                ValidationIssue(
                    "actual_amount_paise",
                    "invalid_type",
                    "actual_amount must be Money.",
                )
            )
        issues.extend(_validate_aware_timestamp(self.completed_at, "completed_at"))
        if issues:
            raise DomainValidationError(issues)

