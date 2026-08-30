"""Structured exceptions for the Phase-12 AI agent orchestration layer."""

from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """Base error for all agent orchestration exceptions."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": "agent_error",
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class UnknownToolError(AgentError):
    """Raised when an unapproved or unregistered tool is requested."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            code="unknown_tool",
            message=f"Tool '{tool_name}' is not in the approved agent tool allowlist.",
            details={"requested_tool": tool_name},
        )


class InvalidToolArgumentsError(AgentError):
    """Raised when tool arguments fail strict schema validation."""

    def __init__(self, tool_name: str, reason: str, invalid_arguments: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="invalid_tool_arguments",
            message=f"Invalid arguments for tool '{tool_name}': {reason}",
            details={"tool_name": tool_name, "reason": reason, "arguments": invalid_arguments or {}},
        )


class ToolOrderError(AgentError):
    """Raised when tools are invoked in an invalid dependency order."""

    def __init__(self, tool_name: str, missing_dependency: str) -> None:
        super().__init__(
            code="tool_order_violation",
            message=f"Cannot execute '{tool_name}' before '{missing_dependency}' is completed.",
            details={"tool_name": tool_name, "missing_dependency": missing_dependency},
        )


class ToolExecutionError(AgentError):
    """Raised when an underlying deterministic service encounters an execution error."""

    def __init__(self, tool_name: str, inner_exception: Exception) -> None:
        super().__init__(
            code="tool_execution_failed",
            message=f"Execution of tool '{tool_name}' failed: {inner_exception}",
            details={"tool_name": tool_name, "inner_error": str(inner_exception)},
        )


class StepLimitExceededError(AgentError):
    """Raised when the agent loop exceeds the maximum allowed iterations."""

    def __init__(self, step_count: int, max_steps: int) -> None:
        super().__init__(
            code="step_limit_exceeded",
            message=f"Agent exceeded maximum step limit of {max_steps} iterations (reached step {step_count}).",
            details={"step_count": step_count, "max_steps": max_steps},
        )


class InvalidAgentResponseError(AgentError):
    """Raised when the agent model returns an invalid or unparseable action."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            code="invalid_agent_response",
            message=f"Agent model produced an invalid response: {reason}",
            details={"reason": reason},
        )


class DecisionConsistencyError(AgentError):
    """Raised when an agent output or explanation mutates authoritative optimizer facts."""

    def __init__(self, field_name: str, expected_value: Any, actual_value: Any) -> None:
        super().__init__(
            code="decision_consistency_violation",
            message=f"Consistency check failed on '{field_name}': expected {expected_value}, got {actual_value}.",
            details={"field": field_name, "expected": expected_value, "actual": actual_value},
        )
