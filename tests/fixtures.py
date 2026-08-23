"""Small deterministic Phase 2 fixtures; these are not a simulator."""

from datetime import datetime
from decimal import Decimal

from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import SupportedCity


def make_context(
    transaction_id: str = "TXN-001", amount_paise: int = 65000
) -> RideTransactionContext:
    return RideTransactionContext(
        transaction_id=transaction_id,
        customer_id=f"C-{transaction_id}",
        estimated_amount=Money(amount_paise=amount_paise),
        city=SupportedCity.HYDERABAD,
        distance_km=Decimal("18.4"),
        estimated_duration_minutes=42,
        surge_multiplier=Decimal("1.18"),
        timestamp=datetime.fromisoformat("2026-08-23T18:30:00+05:30"),
    )


def make_outcome(
    transaction_id: str = "TXN-001", amount_paise: int = 62000
) -> RideTransactionOutcome:
    return RideTransactionOutcome(
        transaction_id=transaction_id,
        actual_amount=Money(amount_paise=amount_paise),
        completed_at=datetime.fromisoformat("2026-08-23T19:20:00+05:30"),
    )


def baseline_fixture() -> tuple[
    tuple[RideTransactionContext, ...], tuple[RideTransactionOutcome, ...]
]:
    return (
        (
            make_context("TXN-001", 65000),
            make_context("TXN-002", 65000),
            make_context("TXN-003", 50000),
        ),
        (
            make_outcome("TXN-001", 62000),
            make_outcome("TXN-002", 71000),
            make_outcome("TXN-003", 64000),
        ),
    )

