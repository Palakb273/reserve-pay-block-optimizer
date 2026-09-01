"""Explanation Agent that transforms structured decision evidence into human-readable text."""

from __future__ import annotations

from typing import Any

from reserve_pay_optimizer.agents.errors import DecisionConsistencyError
from reserve_pay_optimizer.agents.models import (
    ExplanationAgentResult,
    ReserveAgentDecision,
)
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.explainability.models import ExplanationLevel
from reserve_pay_optimizer.explainability.service import ExplanationService
from reserve_pay_optimizer.optimization.models import OptimizationResult
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import CustomerHistoryProvider
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


class ExplanationAgent:
    """Explains an already-computed ReserveAgentDecision using Phase-9 structured evidence."""

    def __init__(
        self,
        base_model: ConditionalFareDistributionModel,
        personalized_model: ConditionalFareDistributionModel,
        history_provider: CustomerHistoryProvider,
        explanation_service: ExplanationService | None = None,
    ) -> None:
        self.base_model = base_model
        self.personalized_model = personalized_model
        self.history_provider = history_provider
        self.explanation_service = explanation_service or ExplanationService()

    def explain(
        self,
        context: RideTransactionContext,
        decision: ReserveAgentDecision,
    ) -> ExplanationAgentResult:
        """Generates deterministic concise/detailed explanation from structured Phase-9 facts."""
        # Re-derive predictions and policy optimization for fact generation
        predictor = PersonalizedFarePredictor(
            self.base_model,
            self.personalized_model,
            self.history_provider,
        )
        prediction = predictor.predict(context)
        policy = ReserveRiskPolicy.for_profile(decision.risk_profile)
        optimization = PolicyConstrainedOptimizer(ReserveBlockOptimizer()).optimize(
            context, prediction, policy
        )

        # Strict consistency validation
        if optimization.recommended_block.amount_paise != decision.recommended_block.amount_paise:
            raise DecisionConsistencyError(
                "recommended_block",
                decision.recommended_block.amount_paise,
                optimization.recommended_block.amount_paise,
            )
        if optimization.estimated_collection_probability != decision.estimated_collection_probability:
            raise DecisionConsistencyError(
                "estimated_collection_probability",
                decision.estimated_collection_probability,
                optimization.estimated_collection_probability,
            )
        if optimization.objective_score != decision.objective_score:
            raise DecisionConsistencyError(
                "objective_score", decision.objective_score, optimization.objective_score
            )
        if optimization.risk_policy.profile != decision.risk_profile:
            raise DecisionConsistencyError(
                "risk_profile", decision.risk_profile.value, optimization.risk_policy.profile.value
            )
        if prediction.prediction_mode != decision.prediction_mode:
            raise DecisionConsistencyError(
                "prediction_mode", decision.prediction_mode, prediction.prediction_mode
            )

        concise = self.explanation_service.explain_reserve_decision(
            context, prediction, optimization, ExplanationLevel.CONCISE
        )
        detailed = self.explanation_service.explain_reserve_decision(
            context, prediction, optimization, ExplanationLevel.DETAILED
        )

        facts = detailed.facts.facts_dict()
        confidence_pct = decision.confidence * 100
        confidence_note = f"Modeled collection coverage is {confidence_pct:.1f}%; not a payment outcome guarantee."

        return ExplanationAgentResult(
            transaction_id=decision.transaction_id,
            agent_run_id=decision.agent_run_id,
            explanation_id=detailed.facts.explanation_id,
            summary=concise.text,
            details=detailed.text,
            factors=facts.get("decision_factors", []),
            confidence_note=confidence_note,
            renderer="deterministic_phase_9",
        )
