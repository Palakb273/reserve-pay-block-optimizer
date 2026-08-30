"""Provider-neutral model protocol and action definitions for agent tool-calling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from reserve_pay_optimizer.agents.models import ReserveAgentDecision, ReserveAgentState


class AgentActionType(StrEnum):
    CALL_TOOL = "call_tool"
    FINALIZE = "finalize"


@dataclass(frozen=True, slots=True)
class AgentModelAction:
    action_type: AgentActionType
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    final_decision: ReserveAgentDecision | None = None
    rationale: str | None = None


class AgentModel(Protocol):
    """Protocol for models that decide the next tool-calling action in an agent loop."""

    def next_action(
        self,
        state: ReserveAgentState,
        available_tools: list[str],
    ) -> AgentModelAction:
        """Determines the next action based on current state and allowlisted tools."""
        ...
