"""Reserve Intelligence Agent implementing bounded tool orchestration over core financial services."""

from __future__ import annotations

from typing import Any
import uuid

from reserve_pay_optimizer.agents.deterministic_model import DeterministicAgentModel
from reserve_pay_optimizer.agents.errors import (
    DecisionConsistencyError,
    InvalidAgentResponseError,
    StepLimitExceededError,
)
from reserve_pay_optimizer.agents.models import (
    AgentStateStatus,
    CustomerHistoryToolOutput,
    MerchantHistoryToolOutput,
    OptimizationToolOutput,
    PredictionToolOutput,
    ReserveAgentDecision,
    ReserveAgentRequest,
    ReserveAgentState,
    RiskToolOutput,
)
from reserve_pay_optimizer.agents.protocol import (
    AgentActionType,
    AgentModel,
)
from reserve_pay_optimizer.agents.registry import AgentToolRegistry


class ReserveIntelligenceAgent:
    """Orchestrates approved tools to determine an exact reserve decision without replacing math."""

    DEFAULT_MAX_STEPS = 8

    def __init__(
        self,
        registry: AgentToolRegistry,
        model: AgentModel | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self.registry = registry
        self.model = model or DeterministicAgentModel()
        self.max_steps = max_steps

    def decide(self, request: ReserveAgentRequest) -> ReserveAgentState:
        """Executes the bounded agent loop to gather context, optimize the block, and return final state."""
        run_id = request.agent_run_id or f"RUN-{uuid.uuid4().hex[:12].upper()}"
        state = ReserveAgentState(
            request=request,
            agent_run_id=run_id,
            status=AgentStateStatus.PENDING,
        )

        for step in range(1, self.max_steps + 1):
            state.step_count = step
            action = self.model.next_action(state, self.registry.available_tools)

            if action.action_type == AgentActionType.CALL_TOOL:
                if not action.tool_name:
                    raise InvalidAgentResponseError("CALL_TOOL action must specify a tool_name.")
                
                # Update status
                if action.tool_name == "get_customer_history":
                    state.status = AgentStateStatus.GATHERING_HISTORY
                elif action.tool_name == "get_transaction_prediction":
                    state.status = AgentStateStatus.PREDICTING
                elif action.tool_name == "calculate_risk":
                    state.status = AgentStateStatus.ASSESSING_RISK
                elif action.tool_name == "optimize_block":
                    state.status = AgentStateStatus.OPTIMIZING

                arguments = action.arguments or {}
                try:
                    result, audit_record = self.registry.execute_tool(
                        action.tool_name, arguments, state
                    )
                except Exception as exc:
                    state.status = AgentStateStatus.FAILED
                    state.error = getattr(exc, "code", type(exc).__name__)
                    setattr(exc, "agent_state", state)
                    raise
                state.tool_calls.append(audit_record)

                # Store tool output in typed state
                if isinstance(result, CustomerHistoryToolOutput):
                    state.customer_history = result
                elif isinstance(result, PredictionToolOutput):
                    state.prediction = result
                elif isinstance(result, RiskToolOutput):
                    state.risk_assessment = result
                elif isinstance(result, OptimizationToolOutput):
                    state.optimization = result
                elif isinstance(result, MerchantHistoryToolOutput):
                    state.merchant_history = result

            elif action.action_type == AgentActionType.FINALIZE:
                state.status = AgentStateStatus.FINALIZING
                if action.final_decision is None:
                    raise InvalidAgentResponseError("FINALIZE action must include a final_decision.")
                
                decision = action.final_decision
                # Strict decision consistency verification against authoritative tool results
                if state.optimization is None:
                    raise DecisionConsistencyError("optimization", "non-null", "null")
                if decision.recommended_block.amount_paise != state.optimization.recommended_block.amount_paise:
                    raise DecisionConsistencyError(
                        "recommended_block",
                        state.optimization.recommended_block.amount_paise,
                        decision.recommended_block.amount_paise,
                    )
                if decision.estimated_collection_probability != state.optimization.estimated_collection_probability:
                    raise DecisionConsistencyError(
                        "estimated_collection_probability",
                        state.optimization.estimated_collection_probability,
                        decision.estimated_collection_probability,
                    )
                if decision.risk_profile != state.request.risk_profile:
                    raise DecisionConsistencyError(
                        "risk_profile",
                        state.request.risk_profile.value,
                        decision.risk_profile.value,
                    )
                if decision.objective_score != state.optimization.objective_score:
                    raise DecisionConsistencyError(
                        "objective_score",
                        state.optimization.objective_score,
                        decision.objective_score,
                    )
                if state.prediction is None:
                    raise DecisionConsistencyError("prediction", "non-null", "null")
                if decision.prediction_mode != state.prediction.prediction_mode:
                    raise DecisionConsistencyError(
                        "prediction_mode",
                        state.prediction.prediction_mode,
                        decision.prediction_mode,
                    )

                state.decision = decision
                state.status = AgentStateStatus.COMPLETED
                return state
            else:
                raise InvalidAgentResponseError(f"Unknown action type '{action.action_type}'.")

        # Exceeded max steps
        state.status = AgentStateStatus.FAILED
        state.error = f"Step limit exceeded ({self.max_steps})"
        raise StepLimitExceededError(self.max_steps + 1, self.max_steps)
