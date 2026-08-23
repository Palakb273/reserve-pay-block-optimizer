"""Typed, monotonic conditional final-fare distribution result."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from math import isfinite
from typing import Mapping

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.config import MAX_AMOUNT_PAISE
from reserve_pay_optimizer.prediction.config import quantile_key


def crossing_count(values: Mapping[Decimal, int]) -> int:
    ordered = [values[quantile] for quantile in sorted(values)]
    return sum(current < previous for previous, current in zip(ordered, ordered[1:]))


def repair_monotonic(values: Mapping[Decimal, int]) -> dict[Decimal, int]:
    """Repair independently modeled quantiles using a cumulative maximum."""

    repaired: dict[Decimal, int] = {}
    running = 0
    for quantile in sorted(values):
        running = max(running, values[quantile])
        repaired[quantile] = running
    return repaired


def ratio_to_paise(estimated_amount_paise: int, predicted_ratio: float) -> int:
    """Cross the ML boundary using Decimal and ceiling to a valid integer paise."""

    if not isfinite(predicted_ratio):
        raise ValueError("model predicted a non-finite fare ratio")
    amount = Decimal(estimated_amount_paise) * Decimal(str(predicted_ratio))
    rounded = int(amount.to_integral_value(rounding=ROUND_CEILING))
    return min(MAX_AMOUNT_PAISE, max(1, rounded))


@dataclass(frozen=True, slots=True)
class FareDistributionPrediction:
    transaction_id: str
    model_version: str
    quantiles: tuple[tuple[Decimal, Money], ...]
    raw_quantile_crossing_detected: bool = False

    def __post_init__(self) -> None:
        probabilities = [probability for probability, _ in self.quantiles]
        amounts = [money.amount_paise for _, money in self.quantiles]
        if probabilities != sorted(probabilities) or len(probabilities) != len(set(probabilities)):
            raise ValueError("quantiles must be unique and sorted")
        if any(not Decimal(0) < probability < Decimal(1) for probability in probabilities):
            raise ValueError("quantiles must be between zero and one")
        if any(current < previous for previous, current in zip(amounts, amounts[1:])):
            raise ValueError("published quantile amounts must be monotonic")

    def amount_for_quantile(self, quantile: Decimal | float | str) -> Money:
        requested = Decimal(str(quantile))
        for probability, amount in self.quantiles:
            if probability == requested:
                return amount
        available = ", ".join(quantile_key(value) for value, _ in self.quantiles)
        raise KeyError(f"quantile {requested} is not modeled; available quantiles: {available}")

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "model_version": self.model_version,
            "quantiles": {
                quantile_key(probability): amount.amount_paise
                for probability, amount in self.quantiles
            },
            "currency": "INR",
            "raw_quantile_crossing_detected": self.raw_quantile_crossing_detected,
        }
