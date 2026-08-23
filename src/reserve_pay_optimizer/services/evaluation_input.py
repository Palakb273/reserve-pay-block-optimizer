"""Parse deterministic Phase 2 JSON datasets into existing domain models."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.services.mobility_validation import (
    parse_mobility_transaction,
)

_OUTCOME_FIELDS = frozenset(
    {"transaction_id", "actual_amount_paise", "completed_at"}
)


def _prefixed(issue: ValidationIssue, prefix: str) -> ValidationIssue:
    return issue.for_field(f"{prefix}.{issue.field}")


def _parse_outcome(payload: Mapping[str, object]) -> RideTransactionOutcome:
    issues: list[ValidationIssue] = []
    for field in sorted(set(payload) - _OUTCOME_FIELDS):
        issues.append(
            ValidationIssue(field, "unknown_field", f"Unknown outcome field: {field}.")
        )

    transaction_id = payload.get("transaction_id")
    if "transaction_id" not in payload:
        issues.append(
            ValidationIssue("transaction_id", "required", "transaction_id is required.")
        )
    elif not isinstance(transaction_id, str):
        issues.append(
            ValidationIssue(
                "transaction_id", "invalid_type", "transaction_id must be a string."
            )
        )
    elif not transaction_id.strip():
        issues.append(
            ValidationIssue(
                "transaction_id", "required", "transaction_id cannot be empty."
            )
        )
    else:
        transaction_id = transaction_id.strip()

    actual_amount: Money | None = None
    if "actual_amount_paise" not in payload:
        issues.append(
            ValidationIssue(
                "actual_amount_paise", "required", "actual_amount_paise is required."
            )
        )
    else:
        try:
            actual_amount = Money(amount_paise=payload["actual_amount_paise"])  # type: ignore[arg-type]
        except DomainValidationError as exc:
            issues.extend(
                issue.for_field("actual_amount_paise") for issue in exc.issues
            )

    completed_at: datetime | None = None
    value = payload.get("completed_at")
    if "completed_at" not in payload:
        issues.append(
            ValidationIssue("completed_at", "required", "completed_at is required.")
        )
    elif not isinstance(value, str):
        issues.append(
            ValidationIssue(
                "completed_at",
                "invalid_type",
                "completed_at must be an RFC 3339 string.",
            )
        )
    else:
        try:
            completed_at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            issues.append(
                ValidationIssue(
                    "completed_at",
                    "invalid_timestamp",
                    "completed_at must be a valid RFC 3339 datetime.",
                )
            )
        else:
            if completed_at.tzinfo is None or completed_at.utcoffset() is None:
                issues.append(
                    ValidationIssue(
                        "completed_at",
                        "timezone_required",
                        "completed_at must include a UTC offset.",
                    )
                )

    if issues:
        raise DomainValidationError(issues)
    return RideTransactionOutcome(
        transaction_id=transaction_id,  # type: ignore[arg-type]
        actual_amount=actual_amount,  # type: ignore[arg-type]
        completed_at=completed_at,  # type: ignore[arg-type]
    )


def parse_evaluation_dataset(
    payload: Mapping[str, object],
) -> tuple[tuple[RideTransactionContext, ...], tuple[RideTransactionOutcome, ...]]:
    """Parse records while keeping transaction context and outcome separate."""

    if not isinstance(payload, Mapping):
        raise DomainValidationError(
            [ValidationIssue("$", "invalid_type", "Dataset must be a JSON object.")]
        )
    issues: list[ValidationIssue] = []
    for field in sorted(set(payload) - {"records"}):
        issues.append(
            ValidationIssue(field, "unknown_field", f"Unknown dataset field: {field}.")
        )
    records = payload.get("records")
    if "records" not in payload:
        issues.append(ValidationIssue("records", "required", "records is required."))
    elif not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        issues.append(
            ValidationIssue("records", "invalid_type", "records must be a JSON array.")
        )
    if issues:
        raise DomainValidationError(issues)

    transactions: list[RideTransactionContext] = []
    outcomes: list[RideTransactionOutcome] = []
    for index, record in enumerate(records):  # type: ignore[union-attr]
        prefix = f"records[{index}]"
        if not isinstance(record, Mapping):
            issues.append(
                ValidationIssue(prefix, "invalid_type", "Each record must be an object.")
            )
            continue
        for field in sorted(set(record) - {"transaction", "outcome"}):
            issues.append(
                ValidationIssue(
                    f"{prefix}.{field}",
                    "unknown_field",
                    f"Unknown evaluation record field: {field}.",
                )
            )

        transaction_payload = record.get("transaction")
        if not isinstance(transaction_payload, Mapping):
            issues.append(
                ValidationIssue(
                    f"{prefix}.transaction",
                    "required",
                    "transaction must be an object.",
                )
            )
        else:
            try:
                transactions.append(parse_mobility_transaction(transaction_payload))
            except DomainValidationError as exc:
                issues.extend(
                    _prefixed(issue, f"{prefix}.transaction") for issue in exc.issues
                )

        outcome_payload = record.get("outcome")
        if not isinstance(outcome_payload, Mapping):
            issues.append(
                ValidationIssue(
                    f"{prefix}.outcome",
                    "required",
                    "outcome must be an object.",
                )
            )
        else:
            try:
                outcomes.append(_parse_outcome(outcome_payload))
            except DomainValidationError as exc:
                issues.extend(
                    _prefixed(issue, f"{prefix}.outcome") for issue in exc.issues
                )

    if issues:
        raise DomainValidationError(issues)
    return tuple(transactions), tuple(outcomes)

