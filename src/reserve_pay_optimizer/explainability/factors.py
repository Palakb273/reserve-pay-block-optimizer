"""Deterministic factual factor construction without causal attribution."""

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.explainability.models import (
    ExplanationFactor,
    ExplanationFactorCode,
    FactorDirection,
    HistorySummary,
)
from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy


def static_factors(
    transaction: RideTransactionContext,
    policy: ReserveRiskPolicy,
    history: HistorySummary | None,
    prediction_mode: str,
) -> tuple[ExplanationFactor, ...]:
    factors = [
        ExplanationFactor(
            ExplanationFactorCode.BASE_ESTIMATE,
            "Current fare estimate",
            FactorDirection.CONTEXT,
            (("estimated_amount_paise", transaction.estimated_amount.amount_paise),),
        ),
        ExplanationFactor(
            ExplanationFactorCode.PREDICTED_UNCERTAINTY,
            "Predicted final-fare uncertainty",
            FactorDirection.HIGHER_BLOCK,
            (("interpretation", "upper quantiles are increasingly conservative modeled estimates"),),
        ),
        ExplanationFactor(
            ExplanationFactorCode.MERCHANT_RISK_POLICY,
            "Merchant risk policy",
            FactorDirection.HIGHER_BLOCK,
            (
                ("profile", policy.profile.value),
                ("minimum_modeled_coverage", str(policy.target_collection_probability)),
            ),
        ),
        ExplanationFactor(
            ExplanationFactorCode.OPTIMIZATION_TRADEOFF,
            "Configured optimization trade-off",
            FactorDirection.TRADEOFF,
            (("components", "under-block risk, expected excess block, customer friction"),),
        ),
        ExplanationFactor(
            ExplanationFactorCode.DISTANCE,
            "Projected ride distance",
            FactorDirection.CONTEXT,
            (("distance_km", format(transaction.distance_km, "f")),),
        ),
        ExplanationFactor(
            ExplanationFactorCode.DURATION,
            "Projected ride duration",
            FactorDirection.CONTEXT,
            (("estimated_duration_minutes", transaction.estimated_duration_minutes),),
        ),
        ExplanationFactor(
            ExplanationFactorCode.TIME_CONTEXT,
            "Ride time context",
            FactorDirection.CONTEXT,
            (("ride_start", transaction.timestamp.isoformat()),),
        ),
    ]
    if transaction.surge_multiplier != 1:
        factors.append(
            ExplanationFactor(
                ExplanationFactorCode.SURGE,
                "Observed surge multiplier",
                FactorDirection.CONTEXT,
                (("surge_multiplier", format(transaction.surge_multiplier, "f")),),
            )
        )
    if prediction_mode == "personalized" and history is not None:
        factors.append(
            ExplanationFactor(
                ExplanationFactorCode.CUSTOMER_HISTORY,
                "Aggregated completed-ride history",
                FactorDirection.CONTEXT,
                (
                    ("completed_ride_count", history.completed_ride_count),
                    ("mean_fare_ratio", format_ratio(history.mean_fare_ratio)),
                    ("overrun_rate", format_ratio(history.overrun_rate)),
                ),
            )
        )
    else:
        factors.append(
            ExplanationFactor(
                ExplanationFactorCode.COLD_START,
                "Customer-history cold start",
                FactorDirection.CONTEXT,
                (
                    ("completed_ride_count", history.completed_ride_count if history else 0),
                    ("minimum_required", MINIMUM_PERSONALIZATION_HISTORY),
                    ("prediction_model", "base"),
                ),
            )
        )
    return tuple(factors)
