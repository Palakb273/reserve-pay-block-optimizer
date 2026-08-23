"""One gradient-boosted quantile regressor per configured probability."""

from decimal import Decimal
from typing import Mapping

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.prediction.baseline import GlobalQuantileBaseline
from reserve_pay_optimizer.prediction.config import (
    MODEL_VERSION,
    QUANTILES,
    ModelConfig,
    quantile_key,
)
from reserve_pay_optimizer.prediction.dataset import PredictionRecord
from reserve_pay_optimizer.prediction.distribution import (
    FareDistributionPrediction,
    crossing_count,
    ratio_to_paise,
    repair_monotonic,
)
from reserve_pay_optimizer.prediction.features import PredictionFeatureExtractor


class ConditionalFareDistributionModel:
    """Conditional fare-ratio quantiles converted to safe final paise amounts."""

    def __init__(
        self,
        config: ModelConfig | None = None,
        *,
        quantile_models: Mapping[str, GradientBoostingRegressor] | None = None,
        baseline: GlobalQuantileBaseline | None = None,
    ) -> None:
        self.config = config or ModelConfig()
        self.feature_extractor = PredictionFeatureExtractor()
        self.quantile_models = dict(quantile_models or {})
        self.baseline = baseline

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    @property
    def is_fitted(self) -> bool:
        return all(quantile_key(value) in self.quantile_models for value in QUANTILES)

    def fit(self, records: tuple[PredictionRecord, ...]) -> "ConditionalFareDistributionModel":
        if not records:
            raise ValueError("model training requires at least one record")
        contexts = tuple(record.context for record in records)
        features = self.feature_extractor.transform(contexts)
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
        self.baseline = GlobalQuantileBaseline.fit(records)
        return self

    def predict_raw_amounts(self, context: RideTransactionContext) -> dict[Decimal, int]:
        if not self.is_fitted:
            raise RuntimeError("conditional fare-distribution model is not fitted")
        features = self.feature_extractor.transform((context,))
        return {
            quantile: ratio_to_paise(
                context.estimated_amount.amount_paise,
                float(self.quantile_models[quantile_key(quantile)].predict(features)[0]),
            )
            for quantile in QUANTILES
        }

    def predict(self, context: RideTransactionContext) -> FareDistributionPrediction:
        raw = self.predict_raw_amounts(context)
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
