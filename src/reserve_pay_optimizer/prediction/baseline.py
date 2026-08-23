"""Context-free global fare-ratio quantile prediction baseline."""

from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.dataset import PredictionRecord
from reserve_pay_optimizer.prediction.distribution import ratio_to_paise


@dataclass(frozen=True, slots=True)
class GlobalQuantileBaseline:
    """Training-set empirical ratios applied identically to every context."""

    ratios: tuple[tuple[Decimal, float], ...]

    @classmethod
    def fit(cls, records: tuple[PredictionRecord, ...]) -> "GlobalQuantileBaseline":
        if not records:
            raise ValueError("global baseline requires at least one training record")
        targets = np.asarray([float(record.fare_ratio) for record in records])
        ratios = tuple(
            (quantile, float(np.quantile(targets, float(quantile), method="linear")))
            for quantile in QUANTILES
        )
        return cls(ratios=ratios)

    def predict_amounts(self, context: RideTransactionContext) -> dict[Decimal, int]:
        return {
            quantile: ratio_to_paise(
                context.estimated_amount.amount_paise,
                ratio,
            )
            for quantile, ratio in self.ratios
        }

    def to_dict(self) -> dict[str, str]:
        return {f"{quantile:.2f}": format(ratio, ".17g") for quantile, ratio in self.ratios}

    @classmethod
    def from_dict(cls, values: dict[str, object]) -> "GlobalQuantileBaseline":
        return cls(
            ratios=tuple(
                (Decimal(key), float(value))
                for key, value in sorted(values.items(), key=lambda item: Decimal(item[0]))
            )
        )
