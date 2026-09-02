"""Chronological base-vs-personalized prediction and reserve diagnostics."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from reserve_pay_optimizer.domain.evaluation import StrategyMetrics, format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.personalization.config import (
    MINIMUM_PERSONALIZATION_HISTORY,
    OVERRUN_PRONE_MIN_MEAN_RATIO,
    OVERRUN_PRONE_MIN_RATE,
    STABLE_MAX_MEAN_DISTANCE_FROM_ONE,
    STABLE_MAX_STDDEV,
    VARIABLE_MIN_STDDEV,
)
from reserve_pay_optimizer.personalization.dataset import PersonalizedPredictionRecord
from reserve_pay_optimizer.personalization.model import PersonalizedConditionalFareDistributionModel
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.dataset import PredictionRecord
from reserve_pay_optimizer.prediction.evaluation import PredictionMetrics, calculate_prediction_metrics
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel
from reserve_pay_optimizer.services.evaluation import aggregate_evaluations, evaluate_transaction


def _mean_absolute_calibration_error(metrics: PredictionMetrics) -> Decimal:
    return sum(
        (item.absolute_calibration_error for _, item in metrics.quantiles), Decimal(0)
    ) / Decimal(len(metrics.quantiles))


def _prediction_records(
    records: tuple[PersonalizedPredictionRecord, ...],
) -> tuple[PredictionRecord, ...]:
    return tuple(PredictionRecord(record.context, record.outcome) for record in records)


def _personalized_raw_predictor(
    personalized_model: PersonalizedConditionalFareDistributionModel,
    base_model: ConditionalFareDistributionModel,
    by_transaction_id: dict[str, PersonalizedPredictionRecord],
):
    def predict(record: PredictionRecord):
        personalized_record = by_transaction_id[record.context.transaction_id]
        if (
            personalized_record.history.completed_ride_count
            < MINIMUM_PERSONALIZATION_HISTORY
        ):
            return base_model.predict_raw_amounts(record.context)
        return personalized_model.predict_raw_amounts(
            record.context, personalized_record.history
        )

    return predict


def _calculate_pair(
    records: tuple[PersonalizedPredictionRecord, ...],
    base_model: ConditionalFareDistributionModel,
    personalized_model: PersonalizedConditionalFareDistributionModel,
) -> tuple[PredictionMetrics, PredictionMetrics]:
    prediction_records = _prediction_records(records)
    by_id = {record.context.transaction_id: record for record in records}
    base = calculate_prediction_metrics(
        prediction_records,
        lambda record: base_model.predict_raw_amounts(record.context),
    )
    personalized = calculate_prediction_metrics(
        prediction_records,
        _personalized_raw_predictor(personalized_model, base_model, by_id),
    )
    return base, personalized


@dataclass(frozen=True, slots=True)
class CohortEvaluation:
    record_count: int
    fallback_record_count: int
    personalized_record_count: int
    base: PredictionMetrics
    personalized: PredictionMetrics

    def to_dict(self) -> dict[str, object]:
        base_values = self.base.to_dict()
        personalized_values = self.personalized.to_dict()
        return {
            "record_count": self.record_count,
            "fallback_record_count": self.fallback_record_count,
            "personalized_record_count": self.personalized_record_count,
            "base_mean_pinball_loss_paise": base_values["mean_pinball_loss_paise"],
            "personalized_mean_pinball_loss_paise": personalized_values["mean_pinball_loss_paise"],
            "base_q97_coverage": base_values["quantiles"]["0.97"]["observed_coverage"],
            "personalized_q97_coverage": personalized_values["quantiles"]["0.97"]["observed_coverage"],
            "low_sample_size": self.record_count < 100,
            "base": base_values,
            "personalized": personalized_values,
        }


def _cohort(
    records: tuple[PersonalizedPredictionRecord, ...],
    base_model: ConditionalFareDistributionModel,
    personalized_model: PersonalizedConditionalFareDistributionModel,
) -> CohortEvaluation:
    base, personalized = _calculate_pair(records, base_model, personalized_model)
    personalized_count = sum(
        record.history.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
        for record in records
    )
    return CohortEvaluation(
        record_count=len(records),
        fallback_record_count=len(records) - personalized_count,
        personalized_record_count=personalized_count,
        base=base,
        personalized=personalized,
    )


def _average_block(metrics: StrategyMetrics) -> Money:
    amount = int(
        (
            Decimal(metrics.total_blocked_amount.amount_paise)
            / Decimal(metrics.transaction_count)
        ).to_integral_value(rounding=ROUND_HALF_UP)
    )
    return Money(amount_paise=amount)


def _downstream_balanced(
    records: tuple[PersonalizedPredictionRecord, ...],
    base_model: ConditionalFareDistributionModel,
    personalized_model: PersonalizedConditionalFareDistributionModel,
) -> dict[str, object]:
    optimizer = PolicyConstrainedOptimizer()
    policy = ReserveRiskPolicy.for_profile(RiskProfile.BALANCED)
    base_evaluations = []
    personalized_evaluations = []
    for record in records:
        base_prediction = base_model.predict(record.context)
        if record.history.completed_ride_count < MINIMUM_PERSONALIZATION_HISTORY:
            personalized_prediction = base_prediction
        else:
            personalized_prediction = personalized_model.predict(
                record.context, record.history
            )
        base_result = optimizer.optimize(record.context, base_prediction, policy)
        personalized_result = optimizer.optimize(
            record.context, personalized_prediction, policy
        )
        base_evaluations.append(
            evaluate_transaction(record.context, base_result.reserve_decision, record.outcome)
        )
        personalized_evaluations.append(
            evaluate_transaction(
                record.context, personalized_result.reserve_decision, record.outcome
            )
        )
    base_metrics = aggregate_evaluations(base_evaluations)
    personalized_metrics = aggregate_evaluations(personalized_evaluations)
    base_value = base_metrics.to_dict()
    personalized_value = personalized_metrics.to_dict()
    base_value["average_block_paise"] = _average_block(base_metrics).amount_paise
    personalized_value["average_block_paise"] = _average_block(
        personalized_metrics
    ).amount_paise
    return {
        "risk_profile": "balanced",
        "target_collection_probability": "0.970000",
        "base_predictor": base_value,
        "personalized_predictor": personalized_value,
    }


@dataclass(frozen=True, slots=True)
class PersonalizationEvaluation:
    overall: CohortEvaluation
    history_depth: tuple[tuple[str, CohortEvaluation], ...]
    observed_segments: tuple[tuple[str, CohortEvaluation], ...]
    downstream_balanced_policy: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        base = self.overall.base
        personalized = self.overall.personalized
        history_depth: dict[str, object] = {
            name: {
                "record_count": 0,
                "fallback_record_count": 0,
                "personalized_record_count": 0,
                "base": None,
                "personalized": None,
            }
            for name in ("0-2", "3-5", "6-10", "11+")
        }
        history_depth.update(
            {name: evaluation.to_dict() for name, evaluation in self.history_depth}
        )
        return {
            "test_records": self.overall.record_count,
            "eligible_record_count": self.overall.record_count,
            "minimum_personalization_history": MINIMUM_PERSONALIZATION_HISTORY,
            "fallback_record_count": self.overall.fallback_record_count,
            "cold_start_count": self.overall.fallback_record_count,
            "personalized_record_count": self.overall.personalized_record_count,
            "fallback_percentage": format_ratio(
                Decimal(self.overall.fallback_record_count)
                / Decimal(self.overall.record_count)
            ),
            "personalized_percentage": format_ratio(
                Decimal(self.overall.personalized_record_count)
                / Decimal(self.overall.record_count)
            ),
            "base_predictor": base.to_dict(),
            "personalized_predictor": personalized.to_dict(),
            "comparison": {
                "mean_pinball_loss_improvement_paise": format_ratio(
                    base.mean_pinball_loss_paise
                    - personalized.mean_pinball_loss_paise
                ),
                "mean_absolute_calibration_error": {
                    "base": format_ratio(_mean_absolute_calibration_error(base)),
                    "personalized": format_ratio(
                        _mean_absolute_calibration_error(personalized)
                    ),
                },
                "base_q97_coverage": base.to_dict()["quantiles"]["0.97"]["observed_coverage"],
                "personalized_q97_coverage": personalized.to_dict()["quantiles"]["0.97"]["observed_coverage"],
                "base_q99_coverage": base.to_dict()["quantiles"]["0.99"]["observed_coverage"],
                "personalized_q99_coverage": personalized.to_dict()["quantiles"]["0.99"]["observed_coverage"],
            },
            "history_depth": history_depth,
            "observed_history_segments": {
                name: evaluation.to_dict() for name, evaluation in self.observed_segments
            },
            "segment_definitions": {
                "historically_stable": (
                    f"count >= {MINIMUM_PERSONALIZATION_HISTORY}, stddev <= {STABLE_MAX_STDDEV}, "
                    f"abs(mean_ratio - 1) <= {STABLE_MAX_MEAN_DISTANCE_FROM_ONE}"
                ),
                "historically_variable": (
                    f"count >= {MINIMUM_PERSONALIZATION_HISTORY}, stddev >= {VARIABLE_MIN_STDDEV}"
                ),
                "historically_overrun_prone": (
                    f"count >= {MINIMUM_PERSONALIZATION_HISTORY}, overrun_rate >= {OVERRUN_PRONE_MIN_RATE} "
                    f"and mean_ratio >= 1.02, or mean_ratio >= {OVERRUN_PRONE_MIN_MEAN_RATIO}"
                ),
            },
            "downstream_balanced_policy": self.downstream_balanced_policy,
        }


def evaluate_personalization(
    personalized_model: PersonalizedConditionalFareDistributionModel,
    base_model: ConditionalFareDistributionModel,
    records: tuple[PersonalizedPredictionRecord, ...],
) -> PersonalizationEvaluation:
    if not records:
        raise ValueError("personalization evaluation requires records")
    overall = _cohort(records, base_model, personalized_model)
    buckets = (
        ("0-2", tuple(record for record in records if record.history.completed_ride_count <= 2)),
        ("3-5", tuple(record for record in records if 3 <= record.history.completed_ride_count <= 5)),
        ("6-10", tuple(record for record in records if 6 <= record.history.completed_ride_count <= 10)),
        ("11+", tuple(record for record in records if record.history.completed_ride_count >= 11)),
    )
    history_depth = tuple(
        (name, _cohort(values, base_model, personalized_model))
        for name, values in buckets
        if values
    )
    stable = tuple(
        record
        for record in records
        if record.history.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
        and record.history.fare_ratio_stddev <= STABLE_MAX_STDDEV
        and abs(record.history.mean_fare_ratio - Decimal(1))
        <= STABLE_MAX_MEAN_DISTANCE_FROM_ONE
    )
    variable = tuple(
        record
        for record in records
        if record.history.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
        and record.history.fare_ratio_stddev >= VARIABLE_MIN_STDDEV
    )
    overrun = tuple(
        record
        for record in records
        if record.history.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
        and (
            (
                record.history.overrun_rate >= OVERRUN_PRONE_MIN_RATE
                and record.history.mean_fare_ratio >= Decimal("1.02")
            )
            or record.history.mean_fare_ratio >= OVERRUN_PRONE_MIN_MEAN_RATIO
        )
    )
    segments = (
        ("historically_stable", stable),
        ("historically_variable", variable),
        ("historically_overrun_prone", overrun),
    )
    return PersonalizationEvaluation(
        overall=overall,
        history_depth=history_depth,
        observed_segments=tuple(
            (name, _cohort(values, base_model, personalized_model))
            for name, values in segments
            if values
        ),
        downstream_balanced_policy=_downstream_balanced(
            records, base_model, personalized_model
        ),
    )
