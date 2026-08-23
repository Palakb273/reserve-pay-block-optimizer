"""Leakage-safe training records, deterministic splitting, and fingerprinting."""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from random import Random

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.prediction.config import (
    QUANTILES,
    TARGET_DEFINITION,
    ModelConfig,
    quantile_key,
)


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    context: RideTransactionContext
    outcome: RideTransactionOutcome

    @property
    def fare_ratio(self) -> Decimal:
        return Decimal(self.outcome.actual_amount.amount_paise) / Decimal(
            self.context.estimated_amount.amount_paise
        )


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    train: tuple[PredictionRecord, ...]
    validation: tuple[PredictionRecord, ...]
    test: tuple[PredictionRecord, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "test": len(self.test),
        }


def build_prediction_records(
    contexts: tuple[RideTransactionContext, ...],
    outcomes: tuple[RideTransactionOutcome, ...],
) -> tuple[PredictionRecord, ...]:
    """Join context/outcome pairs for supervised training without merging schemas."""

    issues: list[ValidationIssue] = []
    context_ids = [context.transaction_id for context in contexts]
    outcome_ids = [outcome.transaction_id for outcome in outcomes]
    if len(context_ids) != len(set(context_ids)):
        issues.append(ValidationIssue("transactions", "duplicate_id", "Transaction IDs must be unique."))
    if len(outcome_ids) != len(set(outcome_ids)):
        issues.append(ValidationIssue("outcomes", "duplicate_id", "Outcome IDs must be unique."))
    missing = set(context_ids) - set(outcome_ids)
    unexpected = set(outcome_ids) - set(context_ids)
    for transaction_id in sorted(missing):
        issues.append(ValidationIssue("outcomes", "missing_outcome", f"Missing outcome for {transaction_id}."))
    for transaction_id in sorted(unexpected):
        issues.append(ValidationIssue("outcomes", "unexpected_outcome", f"Unexpected outcome for {transaction_id}."))
    if issues:
        raise DomainValidationError(issues)
    outcomes_by_id = {outcome.transaction_id: outcome for outcome in outcomes}
    return tuple(
        PredictionRecord(context=context, outcome=outcomes_by_id[context.transaction_id])
        for context in sorted(contexts, key=lambda item: item.transaction_id)
    )


def split_records(
    records: tuple[PredictionRecord, ...], config: ModelConfig
) -> DatasetSplit:
    """Create a seeded 70/15/15 split with no shared records."""

    if len(records) < 3:
        raise ValueError("at least three records are required for train/validation/test splitting")
    shuffled = list(records)
    Random(config.seed).shuffle(shuffled)
    train_count = int(Decimal(len(records)) * config.train_fraction)
    validation_count = int(Decimal(len(records)) * config.validation_fraction)
    train_count = max(1, train_count)
    validation_count = max(1, validation_count)
    if train_count + validation_count >= len(records):
        validation_count = 1
        train_count = len(records) - 2
    return DatasetSplit(
        train=tuple(shuffled[:train_count]),
        validation=tuple(shuffled[train_count : train_count + validation_count]),
        test=tuple(shuffled[train_count + validation_count :]),
    )


def dataset_fingerprint(
    records: tuple[PredictionRecord, ...], config: ModelConfig
) -> str:
    """Hash canonical contents and prediction configuration, never filesystem paths."""

    canonical_records = []
    for record in records:
        context = record.context
        outcome = record.outcome
        canonical_records.append(
            {
                "transaction_id": context.transaction_id,
                "customer_id": context.customer_id,
                "estimated_amount_paise": context.estimated_amount.amount_paise,
                "city": context.city.value,
                "distance_km": str(context.distance_km),
                "estimated_duration_minutes": context.estimated_duration_minutes,
                "surge_multiplier": str(context.surge_multiplier),
                "timestamp": context.timestamp.isoformat(),
                "actual_amount_paise": outcome.actual_amount.amount_paise,
                "completed_at": outcome.completed_at.isoformat(),
            }
        )
    payload = {
        "records": canonical_records,
        "model_config": config.to_dict(),
        "quantiles": [quantile_key(value) for value in QUANTILES],
        "target": TARGET_DEFINITION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()
