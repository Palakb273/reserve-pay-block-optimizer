"""Typed customer-history and personalized-prediction models."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


@dataclass(frozen=True, slots=True)
class CustomerHistoryFeatures:
    customer_id: str
    completed_ride_count: int
    mean_fare_ratio: Decimal
    fare_ratio_stddev: Decimal
    overrun_rate: Decimal
    mean_positive_overrun_ratio: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.customer_id, str) or not self.customer_id.strip():
            raise ValueError("customer_id must be a non-empty string")
        if (
            isinstance(self.completed_ride_count, bool)
            or not isinstance(self.completed_ride_count, int)
            or self.completed_ride_count < 0
        ):
            raise ValueError("completed_ride_count must be a non-negative integer")
        decimal_fields = (
            self.mean_fare_ratio,
            self.fare_ratio_stddev,
            self.overrun_rate,
            self.mean_positive_overrun_ratio,
        )
        if any(not isinstance(value, Decimal) or not value.is_finite() for value in decimal_fields):
            raise ValueError("customer history metrics must be finite Decimal values")
        if self.mean_fare_ratio <= 0:
            raise ValueError("mean_fare_ratio must be positive")
        if self.fare_ratio_stddev < 0 or self.mean_positive_overrun_ratio < 0:
            raise ValueError("history dispersion and overrun magnitude cannot be negative")
        if not Decimal(0) <= self.overrun_rate <= Decimal(1):
            raise ValueError("overrun_rate must be between zero and one")

    @classmethod
    def cold_start(cls, customer_id: str) -> "CustomerHistoryFeatures":
        """Return structural defaults that are never sent to the personalized model."""

        return cls(
            customer_id=customer_id,
            completed_ride_count=0,
            mean_fare_ratio=Decimal(1),
            fare_ratio_stddev=Decimal(0),
            overrun_rate=Decimal(0),
            mean_positive_overrun_ratio=Decimal(0),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "customer_id": self.customer_id,
            "completed_ride_count": self.completed_ride_count,
            "mean_fare_ratio": format_ratio(self.mean_fare_ratio),
            "fare_ratio_stddev": format_ratio(self.fare_ratio_stddev),
            "overrun_rate": format_ratio(self.overrun_rate),
            "mean_positive_overrun_ratio": format_ratio(
                self.mean_positive_overrun_ratio
            ),
        }


@dataclass(frozen=True, slots=True)
class PersonalizedFareDistributionPrediction(FareDistributionPrediction):
    prediction_mode: str = "base"
    history_count: int = 0
    history_as_of: datetime | None = None
    history_features: CustomerHistoryFeatures | None = None

    def __post_init__(self) -> None:
        super(PersonalizedFareDistributionPrediction, self).__post_init__()
        if self.prediction_mode not in {"base", "personalized"}:
            raise ValueError("prediction_mode must be base or personalized")
        if self.history_count < 0:
            raise ValueError("history_count cannot be negative")

    @classmethod
    def from_distribution(
        cls,
        distribution: FareDistributionPrediction,
        *,
        prediction_mode: str,
        history_features: CustomerHistoryFeatures,
        history_as_of: datetime,
    ) -> "PersonalizedFareDistributionPrediction":
        return cls(
            transaction_id=distribution.transaction_id,
            model_version=distribution.model_version,
            quantiles=distribution.quantiles,
            raw_quantile_crossing_detected=(
                distribution.raw_quantile_crossing_detected
            ),
            prediction_mode=prediction_mode,
            history_count=history_features.completed_ride_count,
            history_as_of=history_as_of,
            history_features=history_features,
        )

    def to_dict(self) -> dict[str, object]:
        value = FareDistributionPrediction.to_dict(self)
        value.update(
            {
                "prediction_mode": self.prediction_mode,
                "history_count": self.history_count,
                "history_as_of": (
                    self.history_as_of.isoformat()
                    if self.history_as_of is not None
                    else None
                ),
            }
        )
        return value
