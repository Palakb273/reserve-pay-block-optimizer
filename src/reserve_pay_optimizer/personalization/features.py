"""Behavioral personalization features layered over Phase-4 context features."""

import numpy as np
from numpy.typing import NDArray

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.personalization.config import HISTORY_FEATURE_NAMES
from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.prediction.features import (
    FEATURE_NAMES,
    FORBIDDEN_FEATURE_NAMES,
    PredictionFeatureExtractor,
)

PERSONALIZATION_FORBIDDEN_FEATURE_NAMES = FORBIDDEN_FEATURE_NAMES | frozenset(
    {
        "customer_overrun_bias",
        "customer_variance_multiplier",
        "synthetic_customer_profile",
    }
)
PERSONALIZED_FEATURE_NAMES = (*FEATURE_NAMES, *HISTORY_FEATURE_NAMES)


class PersonalizedFeatureExtractor:
    feature_names = PERSONALIZED_FEATURE_NAMES

    def __init__(self) -> None:
        self.context_extractor = PredictionFeatureExtractor()

    def extract(
        self,
        context: RideTransactionContext,
        history: CustomerHistoryFeatures,
    ) -> tuple[float, ...]:
        if history.customer_id != context.customer_id:
            raise ValueError("history customer_id must match transaction customer_id")
        return (
            *self.context_extractor.extract(context),
            float(history.completed_ride_count),
            float(history.mean_fare_ratio),
            float(history.fare_ratio_stddev),
            float(history.overrun_rate),
            float(history.mean_positive_overrun_ratio),
        )

    def as_mapping(
        self,
        context: RideTransactionContext,
        history: CustomerHistoryFeatures,
    ) -> dict[str, float]:
        return dict(zip(self.feature_names, self.extract(context, history), strict=True))

    def transform(
        self,
        rows: tuple[tuple[RideTransactionContext, CustomerHistoryFeatures], ...],
    ) -> NDArray[np.float64]:
        if not rows:
            return np.empty((0, len(self.feature_names)), dtype=np.float64)
        return np.asarray(
            [self.extract(context, history) for context, history in rows],
            dtype=np.float64,
        )

