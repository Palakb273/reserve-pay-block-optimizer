"""Deterministic tool-calling model following the canonical tool sequence offline."""

from __future__ import annotations

from typing import Any

from reserve_pay_optimizer.agents.models import (
    AgentStateStatus,
    ReasonCode,
    ReserveAgentDecision,
    ReserveAgentState,
)
from reserve_pay_optimizer.agents.protocol import (
    AgentActionType,
    AgentModel,
    AgentModelAction,
)
from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY


class DeterministicAgentModel(AgentModel):
    """Deterministic agent model executing the standard canonical tool orchestration sequence."""

    def next_action(
        self,
        state: ReserveAgentState,
        available_tools: list[str],
    ) -> AgentModelAction:
        if state.customer_history is None:
            return AgentModelAction(
                action_type=AgentActionType.CALL_TOOL,
                tool_name="get_customer_history",
                arguments={"customer_id": state.request.transaction.customer_id},
                rationale="Retrieve completed prior customer history before making a prediction.",
            )

        if state.prediction is None:
            return AgentModelAction(
                action_type=AgentActionType.CALL_TOOL,
                tool_name="get_transaction_prediction",
                arguments={"transaction_id": state.request.transaction.transaction_id},
                rationale="Generate conditional fare distribution quantiles.",
            )

        if state.risk_assessment is None:
            return AgentModelAction(
                action_type=AgentActionType.CALL_TOOL,
                tool_name="calculate_risk",
                arguments={"risk_profile": state.request.risk_profile.value},
                rationale="Assess policy constraints and coverage threshold.",
            )

        if state.optimization is None:
            return AgentModelAction(
                action_type=AgentActionType.CALL_TOOL,
                tool_name="optimize_block",
                arguments={"risk_profile": state.request.risk_profile.value},
                rationale="Optimize reserve block to find the minimal amount satisfying policy.",
            )

        # All tools completed -> finalize decision
        assert state.optimization is not None
        assert state.prediction is not None
        assert state.risk_assessment is not None
        assert state.customer_history is not None

        if state.prediction.prediction_mode == "personalized":
            if state.customer_history.overrun_rate and state.customer_history.overrun_rate > 0:
                reason_code = ReasonCode.PERSONALIZED_OVERRUN_HISTORY
                reason = f"Personalized prediction adjusted for customer history with {state.customer_history.overrun_rate * 100:.0f}% prior overrun rate."
            else:
                reason_code = ReasonCode.PERSONALIZED_STABLE_HISTORY
                reason = "Personalized prediction based on stable completed ride history."
        else:
            reason_code = ReasonCode.COLD_START_BASE_MODEL
            reason = (
                "Base quantile model used because eligible completed history is below "
                f"the shared minimum of {MINIMUM_PERSONALIZATION_HISTORY} rides."
            )

        final_decision = ReserveAgentDecision(
            transaction_id=state.request.transaction.transaction_id,
            agent_run_id=state.agent_run_id,
            recommended_block=state.optimization.recommended_block,
            estimated_collection_probability=state.optimization.estimated_collection_probability,
            estimated_under_block_probability=state.optimization.estimated_under_block_probability,
            risk_profile=state.request.risk_profile,
            risk=state.risk_assessment.risk_level,
            prediction_mode=state.prediction.prediction_mode,
            history_count=state.prediction.history_count,
            model_version=state.prediction.model_version,
            objective_score=state.optimization.objective_score,
            reason_code=reason_code,
            reason=reason,
            confidence=state.optimization.estimated_collection_probability,
            merchant_history_available=False,
            merchant_history=None,
        )

        return AgentModelAction(
            action_type=AgentActionType.FINALIZE,
            final_decision=final_decision,
            rationale="All context gathered and block optimized; finalizing structured decision.",
        )
