"""Auditable decision-time feature extraction shared by training and inference."""

from math import cos, pi, sin

import numpy as np
from numpy.typing import NDArray

from reserve_pay_optimizer.config import INDIA_STANDARD_TIME
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.types import SupportedCity

FORBIDDEN_FEATURE_NAMES = frozenset(
    {
        "transaction_id",
        "customer_id",
        "actual_amount",
        "actual_amount_paise",
        "completed_at",
        "outcome",
        "route_change",
        "traffic_change",
        "pricing_noise",
        "actual_distance",
        "actual_duration",
    }
)

CITY_FEATURE_NAMES = tuple(f"city_{city.value}" for city in SupportedCity)
FEATURE_NAMES = (
    "estimated_amount_paise",
    "distance_km",
    "estimated_duration_minutes",
    "surge_multiplier",
    "hour_sin",
    "hour_cos",
    "day_of_week",
    "is_weekend",
    *CITY_FEATURE_NAMES,
)


class PredictionFeatureExtractor:
    """Convert only `RideTransactionContext` fields to a fixed numeric schema."""

    feature_names = FEATURE_NAMES

    def extract(self, context: RideTransactionContext) -> tuple[float, ...]:
        timestamp = context.timestamp.astimezone(INDIA_STANDARD_TIME)
        hour = timestamp.hour + timestamp.minute / 60 + timestamp.second / 3600
        angle = 2 * pi * hour / 24
        weekday = timestamp.weekday()
        city_values = tuple(float(context.city is city) for city in SupportedCity)
        return (
            float(context.estimated_amount.amount_paise),
            float(context.distance_km),
            float(context.estimated_duration_minutes),
            float(context.surge_multiplier),
            sin(angle),
            cos(angle),
            float(weekday),
            float(weekday >= 5),
            *city_values,
        )

    def as_mapping(self, context: RideTransactionContext) -> dict[str, float]:
        return dict(zip(self.feature_names, self.extract(context), strict=True))

    def transform(
        self, contexts: tuple[RideTransactionContext, ...]
    ) -> NDArray[np.float64]:
        if not contexts:
            return np.empty((0, len(self.feature_names)), dtype=np.float64)
        return np.asarray([self.extract(context) for context in contexts], dtype=np.float64)
