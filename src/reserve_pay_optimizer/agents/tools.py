"""Approved agent tool implementations wrapping existing deterministic services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from reserve_pay_optimizer.agents.errors import ToolExecutionError
from reserve_pay_optimizer.agents.models import (
    CustomerHistoryToolOutput,
    MerchantHistoryToolOutput,
    OptimizationToolOutput,
    PredictionToolOutput,
    RiskLevel,
    RiskToolOutput,
)
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import (
    CustomerHistoryProvider,
    InMemoryCustomerHistoryProvider,
)
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY


def execute_get_customer_history(
    context: RideTransactionContext,
    history_provider: CustomerHistoryProvider,
) -> CustomerHistoryToolOutput:
    """Retrieves causal completed customer history prior to the transaction timestamp."""
    try:
        features = history_provider.features_for(context)
        if features is None or features.completed_ride_count == 0:
            return CustomerHistoryToolOutput(
                customer_id=context.customer_id,
                history_count=0,
                mean_fare_ratio=None,
                fare_ratio_stddev=None,
                overrun_rate=None,
                mean_positive_overrun_ratio=None,
                personalization_eligible=False,
            )
        eligible = features.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
        return CustomerHistoryToolOutput(
            customer_id=context.customer_id,
            history_count=features.completed_ride_count,
            mean_fare_ratio=features.mean_fare_ratio,
            fare_ratio_stddev=features.fare_ratio_stddev,
            overrun_rate=features.overrun_rate,
            mean_positive_overrun_ratio=features.mean_positive_overrun_ratio,
            personalization_eligible=eligible,
        )
    except Exception as exc:
        raise ToolExecutionError("get_customer_history", exc) from exc


def execute_get_transaction_prediction(
    context: RideTransactionContext,
    base_model: ConditionalFareDistributionModel,
    personalized_model: ConditionalFareDistributionModel,
    history_provider: CustomerHistoryProvider,
) -> PredictionToolOutput:
    """Predicts conditional quantiles using base or personalized model via existing predictor."""
    try:
        predictor = PersonalizedFarePredictor(
            base_model,
            personalized_model,
            history_provider,
        )
        prediction = predictor.predict(context)
        quantiles = {
            key: prediction.amount_for_quantile(key).amount_paise
            for key in ("0.05", "0.50", "0.90", "0.95", "0.97", "0.99")
        }
        return PredictionToolOutput(
            prediction_mode=prediction.prediction_mode,
            history_count=prediction.history_count,
            model_version=prediction.model_version,
            quantiles_paise=quantiles,
            lower_interval_paise=quantiles["0.05"],
            upper_interval_paise=quantiles["0.95"],
        )
    except Exception as exc:
        raise ToolExecutionError("get_transaction_prediction", exc) from exc


def execute_calculate_risk(
    risk_profile: RiskProfile,
    prediction_output: PredictionToolOutput,
) -> RiskToolOutput:
    """Evaluates merchant risk policy constraints and assesses deterministic categorical risk."""
    try:
        policy = ReserveRiskPolicy.for_profile(risk_profile)
        target = policy.target_collection_probability
        
        # Deterministic risk mapping based on policy target collection probability
        if target >= Decimal("0.98"):
            risk_level = RiskLevel.LOW
            basis = f"Conservative policy requires {target * 100:.0f}% minimum modeled coverage; under-block risk is minimized."
        elif target >= Decimal("0.95"):
            risk_level = RiskLevel.LOW
            basis = f"Balanced policy requires {target * 100:.0f}% minimum modeled coverage; balanced trade-off between coverage and excess capital."
        else:
            risk_level = RiskLevel.MEDIUM
            basis = f"Aggressive policy targets {target * 100:.0f}% modeled coverage; higher tolerance for under-block in exchange for capital efficiency."

        return RiskToolOutput(
            risk_profile=policy.profile.value,
            target_collection_probability=policy.target_collection_probability,
            risk_level=risk_level,
            risk_basis=basis,
            maximum_modeled_probability=Decimal("0.990000"),
        )
    except Exception as exc:
        raise ToolExecutionError("calculate_risk", exc) from exc


def execute_optimize_block(
    context: RideTransactionContext,
    prediction_output: PredictionToolOutput,
    risk_profile: RiskProfile,
    base_model: ConditionalFareDistributionModel,
    personalized_model: ConditionalFareDistributionModel,
    history_provider: CustomerHistoryProvider,
    optimizer: ReserveBlockOptimizer | None = None,
) -> OptimizationToolOutput:
    """Calculates optimal reserve block using existing Phase-5 optimizer and Phase-6 policy."""
    try:
        opt = optimizer or ReserveBlockOptimizer()
        policy_opt = PolicyConstrainedOptimizer(opt)
        predictor = PersonalizedFarePredictor(
            base_model,
            personalized_model,
            history_provider,
        )
        prediction = predictor.predict(context)
        policy = ReserveRiskPolicy.for_profile(risk_profile)
        optimization = policy_opt.optimize(context, prediction, policy)

        estimated_under_block = Decimal("1.000000") - optimization.estimated_collection_probability
        return OptimizationToolOutput(
            recommended_block=optimization.recommended_block,
            estimated_collection_probability=optimization.estimated_collection_probability,
            estimated_under_block_probability=estimated_under_block,
            expected_excess_block=optimization.expected_excess_block,
            objective_score=optimization.objective_score,
            objective_components={
                "under_block_penalty": optimization.score_components.under_block_component,
                "excess_block_penalty": optimization.score_components.excess_component,
                "friction_penalty": optimization.score_components.friction_component,
            },
            candidate_count=optimization.candidate_count,
        )
    except Exception as exc:
        raise ToolExecutionError("optimize_block", exc) from exc


def execute_get_merchant_history(
    merchant_id: str | None = None,
) -> MerchantHistoryToolOutput:
    """Explicitly reports that merchant history subsystem is not implemented."""
    return MerchantHistoryToolOutput()
