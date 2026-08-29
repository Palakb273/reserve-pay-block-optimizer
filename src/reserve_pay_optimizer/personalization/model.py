"""Personalized gradient-boosted conditional quantile model."""

from decimal import Decimal
from typing import Mapping

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.personalization.config import PERSONALIZED_MODEL_VERSION
from reserve_pay_optimizer.personalization.dataset import PersonalizedPredictionRecord
from reserve_pay_optimizer.personalization.features import PersonalizedFeatureExtractor
from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.prediction.config import QUANTILES, ModelConfig, quantile_key
from reserve_pay_optimizer.prediction.distribution import (
    FareDistributionPrediction,
    crossing_count,
    ratio_to_paise,
    repair_monotonic,
)


class PersonalizedConditionalFareDistributionModel:
    """Learn fare-ratio quantiles from context plus observed history aggregates."""

    def __init__(
        self,
        config: ModelConfig | None = None,
        *,
        quantile_models: Mapping[str, GradientBoostingRegressor] | None = None,
    ) -> None:
        self.config = config or ModelConfig()
        self.feature_extractor = PersonalizedFeatureExtractor()
        self.quantile_models = dict(quantile_models or {})

    @property
    def model_version(self) -> str:
        return PERSONALIZED_MODEL_VERSION

    @property
    def is_fitted(self) -> bool:
        return all(quantile_key(value) in self.quantile_models for value in QUANTILES)

    def fit(
        self,
        records: tuple[PersonalizedPredictionRecord, ...],
    ) -> "PersonalizedConditionalFareDistributionModel":
        if not records:
            raise ValueError("personalized model training requires eligible history records")
        rows = tuple((record.context, record.history) for record in records)
        features = self.feature_extractor.transform(rows)
        targets = np.asarray([float(record.fare_ratio) for record in records], dtype=np.float64)
        fitted: dict[str, GradientBoostingRegressor] = {}
        for quantile in QUANTILES:
            estimator = GradientBoostingRegressor(
                loss="quantile",
                alpha=float(quantile),
                random_state=self.config.seed,
                n_estimators=self.config.n_estimators,
                learning_rate=self.config.learning_rate,
                max_depth=self.config.max_depth,
                min_samples_leaf=self.config.min_samples_leaf,
                subsample=self.config.subsample,
            )
            estimator.fit(features, targets)
            fitted[quantile_key(quantile)] = estimator
        self.quantile_models = fitted
        return self

    def predict_raw_amounts(
        self,
        context: RideTransactionContext,
        history: CustomerHistoryFeatures,
    ) -> dict[Decimal, int]:
        if not self.is_fitted:
            raise RuntimeError("personalized fare-distribution model is not fitted")
        features = self.feature_extractor.transform(((context, history),))
        return {
            quantile: ratio_to_paise(
                context.estimated_amount.amount_paise,
                float(self.quantile_models[quantile_key(quantile)].predict(features)[0]),
            )
            for quantile in QUANTILES
        }

    def predict(
        self,
        context: RideTransactionContext,
        history: CustomerHistoryFeatures,
    ) -> FareDistributionPrediction:
        raw = self.predict_raw_amounts(context, history)
        repaired = repair_monotonic(raw)
        return FareDistributionPrediction(
            transaction_id=context.transaction_id,
            model_version=self.model_version,
            quantiles=tuple(
                (quantile, Money(amount_paise=repaired[quantile]))
                for quantile in QUANTILES
            ),
            raw_quantile_crossing_detected=crossing_count(raw) > 0,
        )

