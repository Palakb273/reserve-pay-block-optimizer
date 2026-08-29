from datetime import datetime, timedelta
from decimal import Decimal

from reserve_pay_optimizer.config import INDIA_STANDARD_TIME
from reserve_pay_optimizer.domain.mobility import RideTransactionContext, RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.personalization.models import (
    CustomerHistoryFeatures,
    PersonalizedFareDistributionPrediction,
)
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


def context(
    *,
    transaction_id: str = "DYN-001",
    customer_id: str = "C-DYN",
    estimate: int = 70000,
) -> RideTransactionContext:
    return RideTransactionContext(
        transaction_id=transaction_id,
        customer_id=customer_id,
        estimated_amount=Money(estimate),
        city=SupportedCity.HYDERABAD,
        distance_km=Decimal("18.0"),
        estimated_duration_minutes=42,
        surge_multiplier=Decimal("1.10"),
        timestamp=datetime(2027, 1, 10, 10, 0, tzinfo=INDIA_STANDARD_TIME),
    )


def outcome(ride: RideTransactionContext, actual: int = 78000) -> RideTransactionOutcome:
    return RideTransactionOutcome(
        ride.transaction_id,
        Money(actual),
        ride.timestamp + timedelta(minutes=70),
    )


class MutableHistoryProvider:
    def __init__(self, history_count: int = 5) -> None:
        self.history_count = history_count

    def features_for(self, transaction):
        return CustomerHistoryFeatures(
            customer_id=transaction.customer_id,
            completed_ride_count=self.history_count,
            mean_fare_ratio=Decimal("1.05"),
            fare_ratio_stddev=Decimal("0.03"),
            overrun_rate=Decimal("0.60"),
            mean_positive_overrun_ratio=Decimal("0.08"),
        )


class DeterministicPersonalizedPredictor:
    """Small decision-time-only predictor with transparent estimate-relative quantiles."""

    def __init__(self, history_count: int = 5) -> None:
        self.history_provider = MutableHistoryProvider(history_count)
        self.min_history = 3
        self.calls = []

    def predict_with_history(self, context, history, *, history_as_of):
        self.calls.append((context, history, history_as_of))
        offsets = (-3000, -2500, -1500, 0, 1000, 3000, 3500, 4000, 5000, 50000)
        distribution = FareDistributionPrediction(
            transaction_id=context.transaction_id,
            model_version="test_dynamic_distribution_v1",
            quantiles=tuple(
                (quantile, Money(max(1, context.estimated_amount.amount_paise + offset)))
                for quantile, offset in zip(QUANTILES, offsets, strict=True)
            ),
        )
        return PersonalizedFareDistributionPrediction.from_distribution(
            distribution,
            prediction_mode=(
                "personalized" if history.completed_ride_count >= self.min_history else "base"
            ),
            history_features=history,
            history_as_of=history_as_of,
        )
