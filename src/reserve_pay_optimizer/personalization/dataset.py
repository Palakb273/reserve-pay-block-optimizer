"""Chronological, completion-aware personalized dataset construction."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import heapq
import json

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.mobility import RideTransactionContext, RideTransactionOutcome
from reserve_pay_optimizer.personalization.config import (
    CHRONOLOGICAL_SPLIT_STRATEGY,
    MINIMUM_PERSONALIZATION_HISTORY,
)
from reserve_pay_optimizer.personalization.history import calculate_customer_history_features
from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.prediction.config import QUANTILES, TARGET_DEFINITION, ModelConfig, quantile_key
from reserve_pay_optimizer.prediction.dataset import PredictionRecord, build_prediction_records


@dataclass(frozen=True, slots=True)
class PersonalizedPredictionRecord:
    context: RideTransactionContext
    outcome: RideTransactionOutcome
    history: CustomerHistoryFeatures

    @property
    def fare_ratio(self) -> Decimal:
        return Decimal(self.outcome.actual_amount.amount_paise) / Decimal(
            self.context.estimated_amount.amount_paise
        )

    @property
    def prediction_mode(self) -> str:
        return (
            "personalized"
            if self.history.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
            else "base"
        )


@dataclass(frozen=True, slots=True)
class ChronologicalDatasetSplit:
    train: tuple[PersonalizedPredictionRecord, ...]
    validation: tuple[PersonalizedPredictionRecord, ...]
    test: tuple[PersonalizedPredictionRecord, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "test": len(self.test),
        }


def build_personalized_records(
    contexts: tuple[RideTransactionContext, ...],
    outcomes: tuple[RideTransactionOutcome, ...],
) -> tuple[PersonalizedPredictionRecord, ...]:
    paired = build_prediction_records(contexts, outcomes)
    malformed = [
        record.context.transaction_id
        for record in paired
        if record.outcome.completed_at < record.context.timestamp
    ]
    if malformed:
        raise DomainValidationError(
            [
                ValidationIssue(
                    "outcomes",
                    "completion_before_start",
                    f"Outcome completes before transaction starts: {transaction_id}.",
                )
                for transaction_id in sorted(malformed)
            ]
        )

    ordered = sorted(
        paired,
        key=lambda record: (record.context.timestamp, record.context.transaction_id),
    )
    completed_by_customer: dict[str, list[PredictionRecord]] = {}
    pending: list[tuple[datetime, str, PredictionRecord]] = []
    result: list[PersonalizedPredictionRecord] = []
    for record in ordered:
        while pending and pending[0][0] < record.context.timestamp:
            _, _, completed = heapq.heappop(pending)
            completed_by_customer.setdefault(completed.context.customer_id, []).append(
                completed
            )
        history_records = completed_by_customer.get(record.context.customer_id, [])
        history = calculate_customer_history_features(
            record.context.customer_id,
            history_records,
        )
        result.append(
            PersonalizedPredictionRecord(record.context, record.outcome, history)
        )
        heapq.heappush(
            pending,
            (
                record.outcome.completed_at,
                record.context.transaction_id,
                record,
            ),
        )
    return tuple(result)


def chronological_split(
    records: tuple[PersonalizedPredictionRecord, ...],
    config: ModelConfig,
) -> ChronologicalDatasetSplit:
    if len(records) < 3:
        raise ValueError("at least three records are required for chronological splitting")
    ordered = tuple(
        sorted(records, key=lambda item: (item.context.timestamp, item.context.transaction_id))
    )
    train_count = max(1, int(Decimal(len(ordered)) * config.train_fraction))
    validation_count = max(1, int(Decimal(len(ordered)) * config.validation_fraction))
    if train_count + validation_count >= len(ordered):
        validation_count = 1
        train_count = len(ordered) - 2
    return ChronologicalDatasetSplit(
        train=ordered[:train_count],
        validation=ordered[train_count : train_count + validation_count],
        test=ordered[train_count + validation_count :],
    )


def personalized_dataset_fingerprint(
    records: tuple[PersonalizedPredictionRecord, ...],
    config: ModelConfig,
) -> str:
    canonical = []
    for record in records:
        canonical.append(
            {
                "transaction": record.context.to_dict(),
                "actual_amount_paise": record.outcome.actual_amount.amount_paise,
                "completed_at": record.outcome.completed_at.isoformat(),
                "history": record.history.to_dict(),
            }
        )
    payload = {
        "records": canonical,
        "model_config": config.to_dict(),
        "quantiles": [quantile_key(value) for value in QUANTILES],
        "target": TARGET_DEFINITION,
        "chronological_split": CHRONOLOGICAL_SPLIT_STRATEGY,
        "minimum_personalization_history": MINIMUM_PERSONALIZATION_HISTORY,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
