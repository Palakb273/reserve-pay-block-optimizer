"""Typed, serializable Phase-8 dynamic ride state and decisions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.personalization.models import (
    CustomerHistoryFeatures,
    PersonalizedFareDistributionPrediction,
)
from reserve_pay_optimizer.policy.models import PolicyOptimizationResult
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy


class RideUpdateReason(StrEnum):
    TRAFFIC_CHANGE = "traffic_change"
    ROUTE_CHANGE = "route_change"
    SURGE_CHANGE = "surge_change"
    FARE_ESTIMATE_CHANGE = "fare_estimate_change"
    MULTIPLE_FACTORS = "multiple_factors"


class DynamicAuditEventType(StrEnum):
    SESSION_STARTED = "session_started"
    CONTEXT_UPDATED = "context_updated"
    REOPTIMIZED = "reoptimized"
    BLOCK_CONFIRMED = "block_confirmed"


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class RideContextUpdate:
    event_id: str
    transaction_id: str
    sequence_number: int
    observed_at: datetime
    reason: RideUpdateReason
    revised_estimated_amount: Money | None = None
    revised_distance_km: Decimal | None = None
    revised_estimated_duration_minutes: int | None = None
    revised_surge_multiplier: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        if not isinstance(self.transaction_id, str) or not self.transaction_id.strip():
            raise ValueError("transaction_id must be a non-empty string")
        if (
            isinstance(self.sequence_number, bool)
            or not isinstance(self.sequence_number, int)
            or self.sequence_number <= 0
        ):
            raise ValueError("sequence_number must be a positive integer")
        if not _aware(self.observed_at):
            raise ValueError("observed_at must be a timezone-aware datetime")
        if not isinstance(self.reason, RideUpdateReason):
            raise ValueError("reason must be a RideUpdateReason")
        revised = (
            self.revised_estimated_amount,
            self.revised_distance_km,
            self.revised_estimated_duration_minutes,
            self.revised_surge_multiplier,
        )
        if all(value is None for value in revised):
            raise ValueError("at least one mutable ride field must be revised")
        if self.revised_estimated_amount is not None and not isinstance(
            self.revised_estimated_amount, Money
        ):
            raise ValueError("revised_estimated_amount must be Money")
        if self.revised_distance_km is not None and (
            not isinstance(self.revised_distance_km, Decimal)
            or not self.revised_distance_km.is_finite()
            or self.revised_distance_km < 0
        ):
            raise ValueError("revised_distance_km must be a finite non-negative Decimal")
        duration = self.revised_estimated_duration_minutes
        if duration is not None and (
            isinstance(duration, bool) or not isinstance(duration, int) or duration < 0
        ):
            raise ValueError(
                "revised_estimated_duration_minutes must be a non-negative integer"
            )
        surge = self.revised_surge_multiplier
        if surge is not None and (
            not isinstance(surge, Decimal) or not surge.is_finite() or surge <= 0
        ):
            raise ValueError("revised_surge_multiplier must be a finite positive Decimal")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "event_id": self.event_id,
            "transaction_id": self.transaction_id,
            "sequence_number": self.sequence_number,
            "observed_at": self.observed_at.isoformat(),
            "reason": self.reason.value,
        }
        if self.revised_estimated_amount is not None:
            value["revised_estimated_amount_paise"] = (
                self.revised_estimated_amount.amount_paise
            )
        if self.revised_distance_km is not None:
            value["revised_distance_km"] = float(self.revised_distance_km)
        if self.revised_estimated_duration_minutes is not None:
            value["revised_estimated_duration_minutes"] = (
                self.revised_estimated_duration_minutes
            )
        if self.revised_surge_multiplier is not None:
            value["revised_surge_multiplier"] = float(self.revised_surge_multiplier)
        return value


@dataclass(frozen=True, slots=True)
class DynamicReoptimizationDecision:
    transaction_id: str
    event_id: str
    sequence_number: int
    session_version: int
    update_reason: RideUpdateReason
    previous_authorized_block: Money
    previous_target_block: Money
    recommended_target_block: Money
    additional_block_required: Money
    current_block_sufficient: bool
    prediction_mode: str
    history_count: int
    risk_policy: ReserveRiskPolicy
    estimated_collection_probability: Decimal
    estimated_under_block_probability: Decimal
    expected_excess_block: Money
    objective_score: Decimal
    model_version: str
    observed_at: datetime
    previous_estimated_amount: Money
    revised_estimated_amount: Money
    previous_distance_km: Decimal
    revised_distance_km: Decimal
    previous_estimated_duration_minutes: int
    revised_estimated_duration_minutes: int
    previous_surge_multiplier: Decimal
    revised_surge_multiplier: Decimal
    previous_q50: Money
    revised_q50: Money
    previous_q90: Money
    revised_q90: Money
    previous_q95: Money
    revised_q95: Money
    previous_q97: Money
    revised_q97: Money
    previous_q99: Money
    revised_q99: Money

    def __post_init__(self) -> None:
        expected = max(
            self.recommended_target_block.amount_paise
            - self.previous_authorized_block.amount_paise,
            0,
        )
        if self.additional_block_required.amount_paise != expected:
            raise ValueError("additional block must equal max(target - authorized, 0)")
        if self.current_block_sufficient != (expected == 0):
            raise ValueError("current_block_sufficient is inconsistent")

    def to_dict(self, *, verbose: bool = False) -> dict[str, object]:
        value: dict[str, object] = {
            "transaction_id": self.transaction_id,
            "event_id": self.event_id,
            "sequence_number": self.sequence_number,
            "session_version": self.session_version,
            "update_reason": self.update_reason.value,
            "previous_authorized_block_paise": self.previous_authorized_block.amount_paise,
            "recommended_target_block_paise": self.recommended_target_block.amount_paise,
            "additional_block_required_paise": self.additional_block_required.amount_paise,
            "current_block_sufficient": self.current_block_sufficient,
            "prediction_mode": self.prediction_mode,
            "history_count": self.history_count,
            "risk_profile": self.risk_policy.profile.value,
            "target_collection_probability": format_ratio(
                self.risk_policy.target_collection_probability
            ),
            "estimated_collection_probability": format_ratio(
                self.estimated_collection_probability
            ),
            "estimated_under_block_probability": format_ratio(
                self.estimated_under_block_probability
            ),
            "expected_excess_block_paise": self.expected_excess_block.amount_paise,
            "objective_score": format_ratio(self.objective_score),
            "model_version": self.model_version,
            "observed_at": self.observed_at.isoformat(),
        }
        if verbose:
            value["diagnostics"] = {
                "previous_estimated_amount_paise": self.previous_estimated_amount.amount_paise,
                "revised_estimated_amount_paise": self.revised_estimated_amount.amount_paise,
                "previous_distance_km": format(self.previous_distance_km, "f"),
                "revised_distance_km": format(self.revised_distance_km, "f"),
                "previous_estimated_duration_minutes": self.previous_estimated_duration_minutes,
                "revised_estimated_duration_minutes": self.revised_estimated_duration_minutes,
                "previous_surge_multiplier": format(self.previous_surge_multiplier, "f"),
                "revised_surge_multiplier": format(self.revised_surge_multiplier, "f"),
                "previous_q50_paise": self.previous_q50.amount_paise,
                "revised_q50_paise": self.revised_q50.amount_paise,
                "previous_q90_paise": self.previous_q90.amount_paise,
                "revised_q90_paise": self.revised_q90.amount_paise,
                "previous_q95_paise": self.previous_q95.amount_paise,
                "revised_q95_paise": self.revised_q95.amount_paise,
                "previous_q97_paise": self.previous_q97.amount_paise,
                "revised_q97_paise": self.revised_q97.amount_paise,
                "previous_q99_paise": self.previous_q99.amount_paise,
                "revised_q99_paise": self.revised_q99.amount_paise,
                "previous_target_block_paise": self.previous_target_block.amount_paise,
            }
        return value


@dataclass(frozen=True, slots=True)
class DynamicAuditRecord:
    event_type: DynamicAuditEventType
    session_version: int
    recorded_at: datetime
    event_id: str | None = None
    authorized_block: Money | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "event_type": self.event_type.value,
            "session_version": self.session_version,
            "recorded_at": self.recorded_at.isoformat(),
        }
        if self.event_id is not None:
            value["event_id"] = self.event_id
        if self.authorized_block is not None:
            value["authorized_block_paise"] = self.authorized_block.amount_paise
        return value


@dataclass(frozen=True, slots=True)
class ProcessedRideUpdate:
    update: RideContextUpdate
    decision: DynamicReoptimizationDecision


@dataclass(frozen=True, slots=True)
class DynamicRideSession:
    transaction_id: str
    initial_context: RideTransactionContext
    current_context: RideTransactionContext
    risk_policy: ReserveRiskPolicy
    initial_authorized_block: Money
    current_authorized_block: Money
    session_version: int
    started_at: datetime
    last_update_at: datetime
    history_snapshot: CustomerHistoryFeatures
    initial_prediction: PersonalizedFareDistributionPrediction
    latest_prediction: PersonalizedFareDistributionPrediction
    initial_optimization: PolicyOptimizationResult
    latest_optimization: PolicyOptimizationResult
    processed_updates: tuple[ProcessedRideUpdate, ...] = ()
    audit_trail: tuple[DynamicAuditRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.transaction_id != self.initial_context.transaction_id:
            raise ValueError("session transaction_id must match initial context")
        if self.current_context.transaction_id != self.transaction_id:
            raise ValueError("current context cannot change transaction identity")
        if self.current_authorized_block.amount_paise < self.initial_authorized_block.amount_paise:
            raise ValueError("current authorized block cannot decrease")
        if self.history_snapshot.customer_id != self.initial_context.customer_id:
            raise ValueError("history snapshot must belong to the ride customer")

    def to_dict(self, *, verbose: bool = False) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "session_version": self.session_version,
            "started_at": self.started_at.isoformat(),
            "last_update_at": self.last_update_at.isoformat(),
            "risk_profile": self.risk_policy.profile.value,
            "target_collection_probability": format_ratio(
                self.risk_policy.target_collection_probability
            ),
            "initial_authorized_block_paise": self.initial_authorized_block.amount_paise,
            "current_authorized_block_paise": self.current_authorized_block.amount_paise,
            "initial_context": self.initial_context.to_dict(),
            "current_context": self.current_context.to_dict(),
            "history_snapshot": self.history_snapshot.to_dict(),
            "history_as_of": self.started_at.isoformat(),
            "prediction_mode": self.latest_prediction.prediction_mode,
            "model_version": self.latest_prediction.model_version,
            "latest_prediction": self.latest_prediction.to_dict(),
            "latest_optimization": self.latest_optimization.to_dict(
                include_candidates=verbose
            ),
            "processed_updates": [
                {
                    "update": item.update.to_dict(),
                    "decision": item.decision.to_dict(verbose=verbose),
                }
                for item in self.processed_updates
            ],
            "audit_trail": [item.to_dict() for item in self.audit_trail],
        }


@dataclass(frozen=True, slots=True)
class DynamicUpdateApplication:
    session: DynamicRideSession
    decision: DynamicReoptimizationDecision
    replayed: bool = False
