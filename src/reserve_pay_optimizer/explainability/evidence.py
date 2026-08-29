"""Build authoritative explanation facts from existing calculated outputs."""

from dataclasses import replace
from decimal import Decimal

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.dynamic.models import (
    DynamicAuditEventType,
    DynamicReoptimizationDecision,
    DynamicRideSession,
)
from reserve_pay_optimizer.explainability.errors import ExplanationConsistencyError
from reserve_pay_optimizer.explainability.factors import static_factors
from reserve_pay_optimizer.explainability.models import (
    AuthorizationStatus,
    CandidateComparison,
    DecisionExplanation,
    DecisionType,
    DynamicContextEvidence,
    DynamicFieldChange,
    ExplanationFactor,
    ExplanationFactorCode,
    FactorDirection,
    HistorySummary,
    PredictionSummary,
    TradeoffSummary,
)
from reserve_pay_optimizer.personalization.models import PersonalizedFareDistributionPrediction
from reserve_pay_optimizer.policy.models import PolicyOptimizationResult
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction

EXPLAINED_QUANTILES = (
    Decimal("0.50"),
    Decimal("0.90"),
    Decimal("0.95"),
    Decimal("0.97"),
    Decimal("0.99"),
)


def _prediction_summary(prediction: FareDistributionPrediction) -> PredictionSummary:
    return PredictionSummary(
        tuple(
            (quantile, prediction.amount_for_quantile(quantile))
            for quantile in EXPLAINED_QUANTILES
        )
    )


def _history_summary(
    prediction: FareDistributionPrediction,
) -> HistorySummary | None:
    if not isinstance(prediction, PersonalizedFareDistributionPrediction):
        return None
    history = prediction.history_features
    if history is None:
        return None
    return HistorySummary(
        completed_ride_count=history.completed_ride_count,
        mean_fare_ratio=history.mean_fare_ratio,
        fare_ratio_stddev=history.fare_ratio_stddev,
        overrun_rate=history.overrun_rate,
        mean_positive_overrun_ratio=history.mean_positive_overrun_ratio,
    )


def build_reserve_decision_evidence(
    transaction: RideTransactionContext,
    prediction: FareDistributionPrediction,
    optimization: PolicyOptimizationResult,
) -> DecisionExplanation:
    if not (
        transaction.transaction_id
        == prediction.transaction_id
        == optimization.transaction_id
    ):
        raise ExplanationConsistencyError("transaction IDs do not match")
    if optimization.model_version != prediction.model_version:
        raise ExplanationConsistencyError("model versions do not match")
    if optimization.recommended_block != optimization.reserve_decision.block_amount:
        raise ExplanationConsistencyError("reserve decision block is inconsistent")
    mode = (
        prediction.prediction_mode
        if isinstance(prediction, PersonalizedFareDistributionPrediction)
        else "base"
    )
    history = _history_summary(prediction)
    policy = optimization.risk_policy
    profile_quantile = prediction.amount_for_quantile(
        policy.target_collection_probability
    )
    candidates = tuple(
        CandidateComparison(
            block_amount=item.block_amount,
            estimated_collection_probability=item.estimated_collection_probability,
            objective_score=item.objective_score,
            selected=item.block_amount == optimization.recommended_block,
        )
        for item in optimization.optimization.top_candidates[:5]
    )
    return DecisionExplanation(
        transaction_id=transaction.transaction_id,
        decision_type=DecisionType.INITIAL_RESERVE,
        recommended_block=optimization.recommended_block,
        estimated_amount=transaction.estimated_amount,
        risk_policy=policy,
        estimated_collection_probability=optimization.estimated_collection_probability,
        expected_excess_block=optimization.expected_excess_block,
        expected_excess_ratio=optimization.expected_excess_block_ratio,
        friction_ratio=optimization.friction_ratio,
        objective_score=optimization.objective_score,
        objective_components=optimization.score_components,
        optimization_config=tuple(
            (key, str(value))
            for key, value in optimization.optimization_config.to_dict().items()
        ),
        prediction_mode=mode,
        model_version=prediction.model_version,
        history_summary=history,
        prediction_summary=_prediction_summary(prediction),
        decision_factors=static_factors(transaction, policy, history, mode),
        tradeoff_summary=TradeoffSummary(
            minimum_feasible_probability=policy.target_collection_probability,
            selected_probability_exceeds_minimum=(
                optimization.estimated_collection_probability
                > policy.target_collection_probability
            ),
            profile_quantile_amount=profile_quantile,
            selected_block_exceeds_profile_quantile=(
                optimization.recommended_block.amount_paise
                > profile_quantile.amount_paise
            ),
        ),
        candidate_comparison=candidates,
    )


def _dynamic_changes(
    decision: DynamicReoptimizationDecision,
) -> tuple[DynamicFieldChange, ...]:
    pairs = (
        (
            "estimated_amount_paise",
            decision.previous_estimated_amount.amount_paise,
            decision.revised_estimated_amount.amount_paise,
        ),
        (
            "distance_km",
            format(decision.previous_distance_km, "f"),
            format(decision.revised_distance_km, "f"),
        ),
        (
            "estimated_duration_minutes",
            decision.previous_estimated_duration_minutes,
            decision.revised_estimated_duration_minutes,
        ),
        (
            "surge_multiplier",
            format(decision.previous_surge_multiplier, "f"),
            format(decision.revised_surge_multiplier, "f"),
        ),
    )
    return tuple(
        DynamicFieldChange(field, previous, revised)
        for field, previous, revised in pairs
        if previous != revised
    )


def build_dynamic_decision_evidence(
    session: DynamicRideSession,
    decision: DynamicReoptimizationDecision,
) -> DecisionExplanation:
    if decision.transaction_id != session.transaction_id:
        raise ExplanationConsistencyError("dynamic decision belongs to another session")
    if decision.session_version != session.session_version:
        raise ExplanationConsistencyError("dynamic decision is not the current session version")
    if session.latest_optimization.recommended_block != decision.recommended_target_block:
        raise ExplanationConsistencyError("dynamic target does not match session optimization")
    base = build_reserve_decision_evidence(
        session.current_context,
        session.latest_prediction,
        session.latest_optimization,
    )
    confirmed = any(
        audit.event_type is DynamicAuditEventType.BLOCK_CONFIRMED
        and audit.event_id == decision.event_id
        and audit.authorized_block is not None
        and audit.authorized_block.amount_paise
        == decision.previous_authorized_block.amount_paise
        + decision.additional_block_required.amount_paise
        for audit in session.audit_trail
    )
    previous_quantiles = PredictionSummary(
        (
            (Decimal("0.50"), decision.previous_q50),
            (Decimal("0.90"), decision.previous_q90),
            (Decimal("0.95"), decision.previous_q95),
            (Decimal("0.97"), decision.previous_q97),
            (Decimal("0.99"), decision.previous_q99),
        )
    )
    revised_quantiles = PredictionSummary(
        (
            (Decimal("0.50"), decision.revised_q50),
            (Decimal("0.90"), decision.revised_q90),
            (Decimal("0.95"), decision.revised_q95),
            (Decimal("0.97"), decision.revised_q97),
            (Decimal("0.99"), decision.revised_q99),
        )
    )
    dynamic_factors: list[ExplanationFactor] = []
    code_by_field = {
        "estimated_amount_paise": ExplanationFactorCode.DYNAMIC_FARE_ESTIMATE_CHANGE,
        "distance_km": ExplanationFactorCode.DYNAMIC_ROUTE_CHANGE,
        "estimated_duration_minutes": ExplanationFactorCode.DYNAMIC_TRAFFIC_CHANGE,
        "surge_multiplier": ExplanationFactorCode.DYNAMIC_SURGE_CHANGE,
    }
    for change in _dynamic_changes(decision):
        dynamic_factors.append(
            ExplanationFactor(
                code=code_by_field[change.field],
                label=f"Updated {change.field.replace('_', ' ')}",
                direction=FactorDirection.CONTEXT,
                evidence=(
                    ("previous", change.previous_value),
                    ("revised", change.revised_value),
                ),
            )
        )
    return replace(
        base,
        decision_type=DecisionType.DYNAMIC_REOPTIMIZATION,
        decision_factors=base.decision_factors + tuple(dynamic_factors),
        dynamic_context=DynamicContextEvidence(
            event_id=decision.event_id,
            sequence_number=decision.sequence_number,
            session_version=decision.session_version,
            update_reason=decision.update_reason.value,
            previous_authorized_block=decision.previous_authorized_block,
            previous_target_block=decision.previous_target_block,
            recommended_target_block=decision.recommended_target_block,
            additional_block_required=decision.additional_block_required,
            current_block_sufficient=decision.current_block_sufficient,
            authorization_status=(
                AuthorizationStatus.SIMULATED_CONFIRMED
                if confirmed
                else AuthorizationStatus.RECOMMENDATION_ONLY
            ),
            changed_fields=_dynamic_changes(decision),
            previous_quantiles=previous_quantiles,
            revised_quantiles=revised_quantiles,
        ),
    )
