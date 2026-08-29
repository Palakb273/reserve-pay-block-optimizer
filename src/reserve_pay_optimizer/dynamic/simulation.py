"""Optional deterministic observable in-ride update simulation."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from hashlib import sha256
from random import Random

from reserve_pay_optimizer.domain.mobility import RideTransactionContext, RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.dynamic.models import RideContextUpdate, RideUpdateReason
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import _fare_paise, simulate_transactions
from reserve_pay_optimizer.simulation.models import GENERATOR_ID

DYNAMIC_GENERATOR_ID = "india_mobility_dynamic_v1"


def _transaction_dict(context: RideTransactionContext) -> dict[str, object]:
    return {
        "transaction_id": context.transaction_id,
        "customer_id": context.customer_id,
        "estimated_amount_paise": context.estimated_amount.amount_paise,
        "city": context.city.value,
        "distance_km": float(context.distance_km),
        "estimated_duration_minutes": context.estimated_duration_minutes,
        "surge_multiplier": float(context.surge_multiplier),
        "timestamp": context.timestamp.isoformat(),
    }


def _outcome_dict(outcome: RideTransactionOutcome) -> dict[str, object]:
    return {
        "transaction_id": outcome.transaction_id,
        "actual_amount_paise": outcome.actual_amount.amount_paise,
        "completed_at": outcome.completed_at.isoformat(),
    }


@dataclass(frozen=True, slots=True)
class DynamicSimulationRecord:
    initial_transaction: RideTransactionContext
    updates: tuple[RideContextUpdate, ...]
    outcome: RideTransactionOutcome

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_transaction": _transaction_dict(self.initial_transaction),
            "updates": [update.to_dict() for update in self.updates],
            "outcome": _outcome_dict(self.outcome),
        }


@dataclass(frozen=True, slots=True)
class DynamicSimulationDataset:
    records: tuple[DynamicSimulationRecord, ...]
    metadata: dict[str, object]

    @property
    def transactions(self) -> tuple[RideTransactionContext, ...]:
        return tuple(record.initial_transaction for record in self.records)

    @property
    def outcomes(self) -> tuple[RideTransactionOutcome, ...]:
        return tuple(record.outcome for record in self.records)

    def to_dict(self) -> dict[str, object]:
        return {
            "metadata": self.metadata,
            "records": [record.to_dict() for record in self.records],
        }


def _event_count(rng: Random) -> int:
    ticket = rng.random()
    if ticket < 0.15:
        return 0
    if ticket < 0.50:
        return 1
    if ticket < 0.85:
        return 2
    return 3


def _record_updates(
    context: RideTransactionContext,
    outcome: RideTransactionOutcome,
    config: SimulationConfig,
) -> tuple[RideContextUpdate, ...]:
    digest = sha256(
        f"{config.seed}:{context.transaction_id}:phase8".encode("utf-8")
    ).digest()
    rng = Random(int.from_bytes(digest[:8], "big"))
    count = _event_count(rng)
    if count == 0:
        return ()
    fare = config.fare_model
    actual_duration = max(
        1, int((outcome.completed_at - context.timestamp).total_seconds() // 60)
    )
    actual_ratio = Decimal(outcome.actual_amount.amount_paise) / Decimal(
        context.estimated_amount.amount_paise
    )
    ratio_signal = max(Decimal("0.70"), min(actual_ratio, Decimal("1.45")))
    current_distance = context.distance_km
    current_duration = context.estimated_duration_minutes
    current_surge = context.surge_multiplier
    current_estimate = context.estimated_amount.amount_paise
    updates: list[RideContextUpdate] = []
    ride_seconds = (outcome.completed_at - context.timestamp).total_seconds()
    for index in range(1, count + 1):
        progress = Decimal(index) / Decimal(count + 1)
        observed_at = context.timestamp + timedelta(
            seconds=ride_seconds * float(progress)
        )
        if index == 1:
            reason = RideUpdateReason.TRAFFIC_CHANGE
            projected = Decimal(context.estimated_duration_minutes) + (
                Decimal(actual_duration - context.estimated_duration_minutes) * progress
            )
            revised_duration = max(
                1, int(projected.to_integral_value(rounding=ROUND_HALF_UP))
            )
            if revised_duration == current_duration:
                revised_duration += 1 if ratio_signal >= 1 else -1
                revised_duration = max(1, revised_duration)
            current_duration = revised_duration
            revised_distance = None
            revised_surge = None
        elif index == 2:
            reason = RideUpdateReason.ROUTE_CHANGE
            distance_factor = Decimal(1) + (ratio_signal - Decimal(1)) * progress * Decimal("0.55")
            revised_value = (context.distance_km * distance_factor).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            if revised_value == current_distance:
                revised_value = max(Decimal("0.1"), revised_value + Decimal("0.1"))
            current_distance = revised_value
            projected = Decimal(context.estimated_duration_minutes) + (
                Decimal(actual_duration - context.estimated_duration_minutes) * progress
            )
            current_duration = max(
                1, int(projected.to_integral_value(rounding=ROUND_HALF_UP))
            )
            revised_distance = current_distance
            revised_duration = current_duration
            revised_surge = None
        else:
            reason = RideUpdateReason.MULTIPLE_FACTORS
            surge_delta = Decimal("0.05") if ratio_signal > Decimal("1.05") else Decimal("-0.05")
            current_surge = max(
                Decimal("0.50"),
                min(fare.maximum_surge_multiplier, current_surge + surge_delta),
            ).quantize(Decimal("0.01"))
            projected = Decimal(context.estimated_duration_minutes) + (
                Decimal(actual_duration - context.estimated_duration_minutes) * progress
            )
            current_duration = max(
                1, int(projected.to_integral_value(rounding=ROUND_HALF_UP))
            )
            revised_distance = None
            revised_duration = current_duration
            revised_surge = current_surge
        revised_estimate = _fare_paise(
            current_distance,
            current_duration,
            current_surge,
            fare,
            ROUND_CEILING,
        )
        if revised_estimate == current_estimate:
            revised_estimate = max(1, revised_estimate + (1 if ratio_signal >= 1 else -1))
        current_estimate = revised_estimate
        updates.append(
            RideContextUpdate(
                event_id=f"{context.transaction_id}-UPDATE-{index}",
                transaction_id=context.transaction_id,
                sequence_number=index,
                observed_at=observed_at,
                reason=reason,
                revised_estimated_amount=Money(revised_estimate),
                revised_distance_km=revised_distance,
                revised_estimated_duration_minutes=revised_duration,
                revised_surge_multiplier=revised_surge,
            )
        )
    return tuple(updates)


def simulate_dynamic_transactions(config: SimulationConfig) -> DynamicSimulationDataset:
    """Reuse the existing simulator, then expose only observable projected updates."""

    base = simulate_transactions(config)
    records = tuple(
        DynamicSimulationRecord(
            initial_transaction=record.transaction,
            updates=_record_updates(record.transaction, record.outcome, config),
            outcome=record.outcome,
        )
        for record in base.records
    )
    update_count = sum(len(record.updates) for record in records)
    return DynamicSimulationDataset(
        records=records,
        metadata={
            "generator": DYNAMIC_GENERATOR_ID,
            "base_generator": GENERATOR_ID,
            "seed": config.seed,
            "transaction_count": config.transaction_count,
            "customer_pool_size": config.customer_pool_size,
            "customer_behavior_enabled": config.customer_behavior_enabled,
            "dynamic_update_count": update_count,
            "observable_update_fields": [
                "revised_estimated_amount_paise",
                "revised_distance_km",
                "revised_estimated_duration_minutes",
                "revised_surge_multiplier",
            ],
            "hidden_simulator_values_exported": False,
            "trajectory_assumption": (
                "projected distance/duration/surge and revised synthetic fare converge "
                "partially toward the completed synthetic trajectory"
            ),
        },
    )
