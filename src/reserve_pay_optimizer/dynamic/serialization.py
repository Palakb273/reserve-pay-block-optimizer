"""Strict JSON parsing boundaries for dynamic scenarios and datasets."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.dynamic.models import RideContextUpdate, RideUpdateReason
from reserve_pay_optimizer.services.evaluation_input import parse_evaluation_dataset
from reserve_pay_optimizer.services.mobility_validation import parse_mobility_transaction

_UPDATE_FIELDS = frozenset(
    {
        "event_id",
        "transaction_id",
        "sequence_number",
        "observed_at",
        "reason",
        "revised_estimated_amount_paise",
        "revised_distance_km",
        "revised_estimated_duration_minutes",
        "revised_surge_multiplier",
    }
)


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise DomainValidationError(
            [ValidationIssue(field, "invalid_type", f"{field} must be numeric.")]
        )
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise DomainValidationError(
            [ValidationIssue(field, "invalid_number", f"{field} must be finite.")]
        ) from exc
    if not result.is_finite():
        raise DomainValidationError(
            [ValidationIssue(field, "invalid_number", f"{field} must be finite.")]
        )
    return result


def parse_ride_context_update(payload: Mapping[str, object]) -> RideContextUpdate:
    if not isinstance(payload, Mapping):
        raise DomainValidationError(
            [ValidationIssue("update", "invalid_type", "Update must be an object.")]
        )
    unknown = sorted(set(payload) - _UPDATE_FIELDS)
    if unknown:
        raise DomainValidationError(
            [
                ValidationIssue(field, "unknown_field", f"Unknown update field: {field}.")
                for field in unknown
            ]
        )
    required = ("event_id", "transaction_id", "sequence_number", "observed_at", "reason")
    missing = [field for field in required if field not in payload]
    if missing:
        raise DomainValidationError(
            [ValidationIssue(field, "required", f"{field} is required.") for field in missing]
        )
    try:
        observed_at = datetime.fromisoformat(
            str(payload["observed_at"]).strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise DomainValidationError(
            [ValidationIssue("observed_at", "invalid_timestamp", "observed_at must be RFC 3339.")]
        ) from exc
    try:
        reason = RideUpdateReason(str(payload["reason"]).strip().casefold())
    except ValueError as exc:
        raise DomainValidationError(
            [ValidationIssue("reason", "unsupported_reason", "Unsupported update reason.")]
        ) from exc
    try:
        return RideContextUpdate(
            event_id=payload["event_id"],  # type: ignore[arg-type]
            transaction_id=payload["transaction_id"],  # type: ignore[arg-type]
            sequence_number=payload["sequence_number"],  # type: ignore[arg-type]
            observed_at=observed_at,
            reason=reason,
            revised_estimated_amount=(
                Money(amount_paise=payload["revised_estimated_amount_paise"])  # type: ignore[arg-type]
                if "revised_estimated_amount_paise" in payload
                else None
            ),
            revised_distance_km=(
                _decimal(payload["revised_distance_km"], "revised_distance_km")
                if "revised_distance_km" in payload
                else None
            ),
            revised_estimated_duration_minutes=payload.get(
                "revised_estimated_duration_minutes"
            ),  # type: ignore[arg-type]
            revised_surge_multiplier=(
                _decimal(payload["revised_surge_multiplier"], "revised_surge_multiplier")
                if "revised_surge_multiplier" in payload
                else None
            ),
        )
    except ValueError as exc:
        raise DomainValidationError(
            [ValidationIssue("update", "invalid_update", str(exc))]
        ) from exc


def parse_dynamic_record(payload: Mapping[str, object]):
    """Parse one record without ever passing its outcome into dynamic services."""

    from reserve_pay_optimizer.dynamic.simulation import DynamicSimulationRecord

    if not isinstance(payload, Mapping):
        raise DomainValidationError(
            [ValidationIssue("record", "invalid_type", "Dynamic record must be an object.")]
        )
    unknown = sorted(set(payload) - {"initial_transaction", "updates", "outcome"})
    if unknown:
        raise DomainValidationError(
            [ValidationIssue(field, "unknown_field", f"Unknown dynamic record field: {field}.") for field in unknown]
        )
    evaluation_payload = {
        "records": [
            {
                "transaction": payload.get("initial_transaction"),
                "outcome": payload.get("outcome"),
            }
        ]
    }
    contexts, outcomes = parse_evaluation_dataset(evaluation_payload)
    updates_payload = payload.get("updates")
    if not isinstance(updates_payload, Sequence) or isinstance(updates_payload, (str, bytes)):
        raise DomainValidationError(
            [ValidationIssue("updates", "invalid_type", "updates must be an array.")]
        )
    updates = tuple(parse_ride_context_update(item) for item in updates_payload)  # type: ignore[arg-type]
    context = contexts[0]
    outcome = outcomes[0]
    for update in updates:
        if update.transaction_id != context.transaction_id:
            raise DomainValidationError(
                [ValidationIssue("updates.transaction_id", "transaction_id_mismatch", "Update must match the initial transaction.")]
            )
        if not context.timestamp < update.observed_at < outcome.completed_at:
            raise DomainValidationError(
                [ValidationIssue("updates.observed_at", "outside_active_ride", "Dynamic updates must occur after start and before completion.")]
            )
    return DynamicSimulationRecord(context, updates, outcome)


def parse_dynamic_dataset(payload: Mapping[str, object]):
    from reserve_pay_optimizer.dynamic.simulation import DynamicSimulationDataset

    if not isinstance(payload, Mapping):
        raise DomainValidationError(
            [ValidationIssue("$", "invalid_type", "Dynamic dataset must be an object.")]
        )
    records = payload.get("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or not records:
        raise DomainValidationError(
            [ValidationIssue("records", "invalid_type", "records must be a non-empty array.")]
        )
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise DomainValidationError(
            [ValidationIssue("metadata", "invalid_type", "metadata must be an object.")]
        )
    return DynamicSimulationDataset(
        records=tuple(parse_dynamic_record(item) for item in records),  # type: ignore[arg-type]
        metadata=dict(metadata),
    )


def parse_dynamic_scenario(payload: Mapping[str, object]):
    if not isinstance(payload, Mapping):
        raise DomainValidationError(
            [ValidationIssue("$", "invalid_type", "Scenario must be an object.")]
        )
    history = payload.get("history")
    if not isinstance(history, Mapping):
        raise DomainValidationError(
            [ValidationIssue("history", "required", "Scenario history must be an evaluation dataset.")]
        )
    record = parse_dynamic_record(
        {
            "initial_transaction": payload.get("initial_transaction"),
            "updates": payload.get("updates"),
            "outcome": payload.get("outcome"),
        }
    )
    history_contexts, history_outcomes = parse_evaluation_dataset(history)
    return record, history_contexts, history_outcomes
