"""Normalize and validate the Phase 1 mobility transaction contract."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from reserve_pay_optimizer.config import (
    INDIA_STANDARD_TIME,
    MOBILITY_DOMAIN,
    SUPPORTED_CURRENCY,
    SUPPORTED_MOBILITY_CITIES,
)
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import SupportedCity

_REQUIRED_FIELDS = (
    "transaction_id",
    "customer_id",
    "estimated_amount_paise",
    "city",
    "distance_km",
    "estimated_duration_minutes",
    "surge_multiplier",
    "timestamp",
)
_ALLOWED_FIELDS = frozenset(_REQUIRED_FIELDS) | frozenset({"domain"})


def _required_text(
    payload: Mapping[str, object], field: str, issues: list[ValidationIssue]
) -> str | None:
    value = payload.get(field)
    if field not in payload:
        issues.append(ValidationIssue(field, "required", f"{field} is required."))
        return None
    if not isinstance(value, str):
        issues.append(
            ValidationIssue(field, "invalid_type", f"{field} must be a string.")
        )
        return None
    normalized = value.strip()
    if not normalized:
        issues.append(ValidationIssue(field, "required", f"{field} cannot be empty."))
        return None
    return normalized


def _money(
    payload: Mapping[str, object], field: str, issues: list[ValidationIssue]
) -> Money | None:
    if field not in payload:
        issues.append(ValidationIssue(field, "required", f"{field} is required."))
        return None
    try:
        return Money(amount_paise=payload[field])  # type: ignore[arg-type]
    except DomainValidationError as exc:
        issues.extend(issue.for_field(field) for issue in exc.issues)
        return None


def _decimal_number(
    payload: Mapping[str, object], field: str, issues: list[ValidationIssue]
) -> Decimal | None:
    if field not in payload:
        issues.append(ValidationIssue(field, "required", f"{field} is required."))
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        issues.append(
            ValidationIssue(field, "invalid_type", f"{field} must be a number.")
        )
        return None
    try:
        normalized = Decimal(str(value))
    except InvalidOperation:
        issues.append(
            ValidationIssue(field, "invalid_number", f"{field} must be a finite number.")
        )
        return None
    if not normalized.is_finite():
        issues.append(
            ValidationIssue(field, "invalid_number", f"{field} must be a finite number.")
        )
        return None
    return normalized


def _duration(
    payload: Mapping[str, object], issues: list[ValidationIssue]
) -> int | None:
    field = "estimated_duration_minutes"
    if field not in payload:
        issues.append(ValidationIssue(field, "required", f"{field} is required."))
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        issues.append(
            ValidationIssue(field, "invalid_type", f"{field} must be an integer.")
        )
        return None
    return value


def _city(
    payload: Mapping[str, object], issues: list[ValidationIssue]
) -> SupportedCity | None:
    field = "city"
    if field not in payload:
        issues.append(ValidationIssue(field, "required", "city is required."))
        return None
    value = payload[field]
    if not isinstance(value, str):
        issues.append(ValidationIssue(field, "invalid_type", "city must be a string."))
        return None
    try:
        city = SupportedCity(value.strip().casefold())
    except ValueError:
        supported = ", ".join(sorted(city.value for city in SUPPORTED_MOBILITY_CITIES))
        issues.append(
            ValidationIssue(
                field,
                "unsupported_city",
                f"city must be one of: {supported}.",
            )
        )
        return None
    return city


def _timestamp(
    payload: Mapping[str, object], issues: list[ValidationIssue]
) -> datetime | None:
    field = "timestamp"
    if field not in payload:
        issues.append(ValidationIssue(field, "required", "timestamp is required."))
        return None
    value = payload[field]
    if not isinstance(value, str):
        issues.append(
            ValidationIssue(field, "invalid_type", "timestamp must be an RFC 3339 string.")
        )
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        issues.append(
            ValidationIssue(
                field,
                "invalid_timestamp",
                "timestamp must be a valid RFC 3339 datetime.",
            )
        )
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        issues.append(
            ValidationIssue(
                field,
                "timezone_required",
                "timestamp must include a UTC offset.",
            )
        )
        return None
    return parsed.astimezone(INDIA_STANDARD_TIME)


def parse_mobility_transaction(
    payload: Mapping[str, object],
) -> RideTransactionContext:
    """Normalize a mapping into the Phase 1 decision-time domain model."""

    if not isinstance(payload, Mapping):
        raise DomainValidationError(
            [
                ValidationIssue(
                    "$", "invalid_type", "Transaction payload must be a JSON object."
                )
            ]
        )

    issues: list[ValidationIssue] = []
    for field in sorted(set(payload) - _ALLOWED_FIELDS):
        issues.append(
            ValidationIssue(field, "unknown_field", f"{field} is not a decision-time field.")
        )

    if "domain" in payload:
        domain = payload["domain"]
        if not isinstance(domain, str) or domain.strip().casefold() != MOBILITY_DOMAIN.value:
            issues.append(
                ValidationIssue(
                    "domain",
                    "unsupported_domain",
                    "Phase 1 supports the mobility domain only.",
                )
            )

    transaction_id = _required_text(payload, "transaction_id", issues)
    customer_id = _required_text(payload, "customer_id", issues)
    estimated_amount = _money(payload, "estimated_amount_paise", issues)
    city = _city(payload, issues)
    distance_km = _decimal_number(payload, "distance_km", issues)
    duration = _duration(payload, issues)
    surge_multiplier = _decimal_number(payload, "surge_multiplier", issues)
    timestamp = _timestamp(payload, issues)

    if distance_km is not None and distance_km < 0:
        issues.append(
            ValidationIssue(
                "distance_km",
                "must_be_non_negative",
                "distance_km must be greater than or equal to zero.",
            )
        )
    if duration is not None and duration < 0:
        issues.append(
            ValidationIssue(
                "estimated_duration_minutes",
                "must_be_non_negative",
                "estimated_duration_minutes must be greater than or equal to zero.",
            )
        )
    if surge_multiplier is not None and surge_multiplier <= 0:
        issues.append(
            ValidationIssue(
                "surge_multiplier",
                "must_be_positive",
                "surge_multiplier must be greater than zero.",
            )
        )

    if issues:
        raise DomainValidationError(issues)

    return RideTransactionContext(
        transaction_id=transaction_id,  # type: ignore[arg-type]
        customer_id=customer_id,  # type: ignore[arg-type]
        estimated_amount=estimated_amount,  # type: ignore[arg-type]
        city=city,  # type: ignore[arg-type]
        distance_km=distance_km,  # type: ignore[arg-type]
        estimated_duration_minutes=duration,  # type: ignore[arg-type]
        surge_multiplier=surge_multiplier,  # type: ignore[arg-type]
        timestamp=timestamp,  # type: ignore[arg-type]
    )


def validate_mobility_transaction(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a normalized response or raise a structured validation error."""

    context = parse_mobility_transaction(payload)
    return {
        "validation_status": "valid",
        "domain": MOBILITY_DOMAIN.value,
        "currency": SUPPORTED_CURRENCY.value,
        "transaction": context.to_dict(),
    }
