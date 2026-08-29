"""Completion-time-safe customer history lookup and aggregation."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.prediction.dataset import PredictionRecord, build_prediction_records


def calculate_customer_history_features(
    customer_id: str,
    records: Sequence[PredictionRecord],
) -> CustomerHistoryFeatures:
    eligible = tuple(
        record for record in records if record.context.customer_id == customer_id
    )
    if not eligible:
        return CustomerHistoryFeatures.cold_start(customer_id)
    ratios = tuple(record.fare_ratio for record in eligible)
    count = Decimal(len(ratios))
    mean = sum(ratios, Decimal(0)) / count
    variance = sum(((ratio - mean) ** 2 for ratio in ratios), Decimal(0)) / count
    stddev = variance.sqrt()
    positive_overruns = tuple(ratio - Decimal(1) for ratio in ratios if ratio > 1)
    return CustomerHistoryFeatures(
        customer_id=customer_id,
        completed_ride_count=len(ratios),
        mean_fare_ratio=mean,
        fare_ratio_stddev=stddev,
        overrun_rate=Decimal(len(positive_overruns)) / count,
        mean_positive_overrun_ratio=(
            sum(positive_overruns, Decimal(0)) / Decimal(len(positive_overruns))
            if positive_overruns
            else Decimal(0)
        ),
    )


class CustomerHistoryProvider(Protocol):
    def features_for(self, transaction: RideTransactionContext) -> CustomerHistoryFeatures:
        ...


class InMemoryCustomerHistoryProvider:
    """Read-only typed history source suitable for CLI and local evaluation."""

    def __init__(
        self,
        contexts: tuple[RideTransactionContext, ...],
        outcomes,
    ) -> None:
        self.records = build_prediction_records(contexts, tuple(outcomes))
        malformed = tuple(
            record.context.transaction_id
            for record in self.records
            if record.outcome.completed_at < record.context.timestamp
        )
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

    def get_completed_history(
        self,
        customer_id: str,
        before_timestamp,
        *,
        current_transaction_id: str | None = None,
    ) -> tuple[PredictionRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self.records
                    if record.context.customer_id == customer_id
                    and record.context.transaction_id != current_transaction_id
                    and record.outcome.completed_at < before_timestamp
                ),
                key=lambda record: (
                    record.outcome.completed_at,
                    record.context.transaction_id,
                ),
            )
        )

    def features_for(self, transaction: RideTransactionContext) -> CustomerHistoryFeatures:
        records = self.get_completed_history(
            transaction.customer_id,
            transaction.timestamp,
            current_transaction_id=transaction.transaction_id,
        )
        return calculate_customer_history_features(transaction.customer_id, records)
