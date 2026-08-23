"""Calibration, pinball, interval, crossing, and India city diagnostics."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.prediction.config import QUANTILES, quantile_key
from reserve_pay_optimizer.prediction.dataset import PredictionRecord
from reserve_pay_optimizer.prediction.distribution import crossing_count, repair_monotonic
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel

METRIC_QUANTUM = Decimal("0.000001")


def _metric(value: Decimal) -> Decimal:
    return value.quantize(METRIC_QUANTUM, rounding=ROUND_HALF_UP)


def _format(value: Decimal) -> str:
    return f"{_metric(value):.6f}"


def pinball_loss(actual_paise: int, predicted_paise: int, quantile: Decimal) -> Decimal:
    error = Decimal(actual_paise - predicted_paise)
    return quantile * error if error >= 0 else (quantile - Decimal(1)) * error


@dataclass(frozen=True, slots=True)
class QuantileMetrics:
    target_coverage: Decimal
    observed_coverage: Decimal
    calibration_error: Decimal
    absolute_calibration_error: Decimal
    pinball_loss_paise: Decimal

    def to_dict(self) -> dict[str, str]:
        return {
            "target_coverage": _format(self.target_coverage),
            "observed_coverage": _format(self.observed_coverage),
            "calibration_error": _format(self.calibration_error),
            "absolute_calibration_error": _format(self.absolute_calibration_error),
            "pinball_loss_paise": _format(self.pinball_loss_paise),
        }


@dataclass(frozen=True, slots=True)
class PredictionMetrics:
    record_count: int
    quantiles: tuple[tuple[Decimal, QuantileMetrics], ...]
    mean_pinball_loss_paise: Decimal
    median_mae_paise: Decimal
    interval_05_95_coverage: Decimal
    interval_05_95_average_width_paise: Decimal
    raw_crossing_record_count: int
    raw_crossing_pair_count: int
    per_city: tuple[tuple[SupportedCity, dict[str, object]], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "quantiles": {quantile_key(q): metric.to_dict() for q, metric in self.quantiles},
            "mean_pinball_loss_paise": _format(self.mean_pinball_loss_paise),
            "median_mae_paise": _format(self.median_mae_paise),
            "prediction_interval_q05_q95": {
                "nominal_coverage": "0.900000",
                "empirical_coverage": _format(self.interval_05_95_coverage),
                "average_width_paise": _format(self.interval_05_95_average_width_paise),
            },
            "raw_quantile_crossing": {
                "record_count": self.raw_crossing_record_count,
                "record_frequency": _format(Decimal(self.raw_crossing_record_count) / Decimal(self.record_count)),
                "adjacent_pair_count": self.raw_crossing_pair_count,
            },
            "per_city": {city.value: values for city, values in self.per_city},
        }


@dataclass(frozen=True, slots=True)
class PredictorEvaluation:
    conditional_model: PredictionMetrics
    global_quantile_baseline: PredictionMetrics

    def to_dict(self) -> dict[str, object]:
        conditional = self.conditional_model
        baseline = self.global_quantile_baseline
        return {
            "test_records": conditional.record_count,
            "conditional_model": conditional.to_dict(),
            "global_quantile_baseline": baseline.to_dict(),
            "comparison": {
                "mean_pinball_loss_improvement_paise": _format(
                    baseline.mean_pinball_loss_paise - conditional.mean_pinball_loss_paise
                ),
                "mean_absolute_calibration_error": {
                    "conditional_model": _format(
                        sum((metric.absolute_calibration_error for _, metric in conditional.quantiles), Decimal(0))
                        / Decimal(len(conditional.quantiles))
                    ),
                    "global_quantile_baseline": _format(
                        sum((metric.absolute_calibration_error for _, metric in baseline.quantiles), Decimal(0))
                        / Decimal(len(baseline.quantiles))
                    ),
                },
            },
        }


def calculate_prediction_metrics(
    records: tuple[PredictionRecord, ...],
    raw_predictor: Callable[[PredictionRecord], dict[Decimal, int]],
) -> PredictionMetrics:
    if not records:
        raise ValueError("prediction evaluation requires at least one record")
    raw_predictions = [raw_predictor(record) for record in records]
    repaired = [repair_monotonic(values) for values in raw_predictions]
    actual = [record.outcome.actual_amount.amount_paise for record in records]
    count = Decimal(len(records))

    quantile_metrics: list[tuple[Decimal, QuantileMetrics]] = []
    for quantile in QUANTILES:
        predictions = [values[quantile] for values in repaired]
        coverage = Decimal(sum(value <= predicted for value, predicted in zip(actual, predictions))) / count
        loss = sum(
            (pinball_loss(value, predicted, quantile) for value, predicted in zip(actual, predictions)),
            Decimal(0),
        ) / count
        error = coverage - quantile
        quantile_metrics.append(
            (
                quantile,
                QuantileMetrics(quantile, coverage, error, abs(error), loss),
            )
        )

    median_predictions = [values[Decimal("0.50")] for values in repaired]
    median_mae = sum(
        (Decimal(abs(value - predicted)) for value, predicted in zip(actual, median_predictions)),
        Decimal(0),
    ) / count
    lowers = [values[Decimal("0.05")] for values in repaired]
    uppers = [values[Decimal("0.95")] for values in repaired]
    interval_coverage = Decimal(
        sum(low <= value <= high for value, low, high in zip(actual, lowers, uppers))
    ) / count
    interval_width = sum(
        (Decimal(high - low) for low, high in zip(lowers, uppers)), Decimal(0)
    ) / count
    mean_pinball = sum((metric.pinball_loss_paise for _, metric in quantile_metrics), Decimal(0)) / Decimal(len(QUANTILES))

    city_metrics: list[tuple[SupportedCity, dict[str, object]]] = []
    for city in SupportedCity:
        indices = [index for index, record in enumerate(records) if record.context.city is city]
        if not indices:
            continue
        city_count = Decimal(len(indices))
        values: dict[str, object] = {"test_record_count": len(indices)}
        for quantile in (Decimal("0.90"), Decimal("0.95"), Decimal("0.97"), Decimal("0.99")):
            coverage = Decimal(
                sum(actual[index] <= repaired[index][quantile] for index in indices)
            ) / city_count
            values[f"q{int(quantile * 100):02d}_coverage"] = _format(coverage)
        total_city_loss = sum(
            (
                pinball_loss(actual[index], repaired[index][quantile], quantile)
                for index in indices
                for quantile in QUANTILES
            ),
            Decimal(0),
        )
        values["mean_pinball_loss_paise"] = _format(
            total_city_loss / (city_count * Decimal(len(QUANTILES)))
        )
        city_metrics.append((city, values))

    crossing_counts = [crossing_count(values) for values in raw_predictions]
    return PredictionMetrics(
        record_count=len(records),
        quantiles=tuple(quantile_metrics),
        mean_pinball_loss_paise=mean_pinball,
        median_mae_paise=median_mae,
        interval_05_95_coverage=interval_coverage,
        interval_05_95_average_width_paise=interval_width,
        raw_crossing_record_count=sum(value > 0 for value in crossing_counts),
        raw_crossing_pair_count=sum(crossing_counts),
        per_city=tuple(city_metrics),
    )


def evaluate_predictor(
    model: ConditionalFareDistributionModel,
    records: tuple[PredictionRecord, ...],
) -> PredictorEvaluation:
    if model.baseline is None:
        raise RuntimeError("trained model does not contain the global quantile baseline")
    conditional = calculate_prediction_metrics(records, lambda record: model.predict_raw_amounts(record.context))
    baseline = calculate_prediction_metrics(records, lambda record: model.baseline.predict_amounts(record.context))
    return PredictorEvaluation(conditional_model=conditional, global_quantile_baseline=baseline)
