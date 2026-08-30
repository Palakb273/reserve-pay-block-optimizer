"""Allowlisted Agent Tool Registry with schema validation and cryptographic audit hashing."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Callable

from reserve_pay_optimizer.agents.errors import (
    InvalidToolArgumentsError,
    ToolOrderError,
    UnknownToolError,
)
from reserve_pay_optimizer.agents.models import (
    CustomerHistoryToolOutput,
    MerchantHistoryToolOutput,
    OptimizationToolOutput,
    PredictionToolOutput,
    ReserveAgentState,
    RiskToolOutput,
    ToolAuditRecord,
)
from reserve_pay_optimizer.agents.tools import (
    execute_calculate_risk,
    execute_get_customer_history,
    execute_get_merchant_history,
    execute_get_transaction_prediction,
    execute_optimize_block,
)
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import CustomerHistoryProvider
from reserve_pay_optimizer.policy.risk import RiskProfile
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


def _compute_fingerprint(data: dict[str, Any]) -> str:
    serialized = json.dumps(data, sort_keys=True, default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


class AgentToolRegistry:
    """Central tool registry enforcing allowlist access, strict typing, and audit tracking."""

    APPROVED_TOOLS = frozenset({
        "get_customer_history",
        "get_transaction_prediction",
        "calculate_risk",
        "optimize_block",
        "get_merchant_history",
    })

    def __init__(
        self,
        base_model: ConditionalFareDistributionModel,
        personalized_model: ConditionalFareDistributionModel,
        history_provider: CustomerHistoryProvider,
        optimizer: ReserveBlockOptimizer | None = None,
    ) -> None:
        self.base_model = base_model
        self.personalized_model = personalized_model
        self.history_provider = history_provider
        self.optimizer = optimizer or ReserveBlockOptimizer()

    @property
    def available_tools(self) -> list[str]:
        return sorted(self.APPROVED_TOOLS)

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        state: ReserveAgentState,
    ) -> tuple[Any, ToolAuditRecord]:
        """Validates dependencies and executes an approved tool with full audit fingerprinting."""
        if tool_name not in self.APPROVED_TOOLS:
            raise UnknownToolError(tool_name)

        started_at = datetime.now(UTC)
        input_fingerprint = _compute_fingerprint(arguments)

        # Enforce tool order and dependencies
        if tool_name == "get_transaction_prediction":
            if state.customer_history is None:
                raise ToolOrderError(tool_name, "get_customer_history")
        elif tool_name == "calculate_risk":
            if state.prediction is None:
                raise ToolOrderError(tool_name, "get_transaction_prediction")
        elif tool_name == "optimize_block":
            if state.prediction is None:
                raise ToolOrderError(tool_name, "get_transaction_prediction")
            if state.risk_assessment is None:
                raise ToolOrderError(tool_name, "calculate_risk")

        # Execute the specific tool
        try:
            if tool_name == "get_customer_history":
                result = execute_get_customer_history(
                    state.request.transaction,
                    self.history_provider,
                )
                output_dict = result.to_dict()
            elif tool_name == "get_transaction_prediction":
                result = execute_get_transaction_prediction(
                    state.request.transaction,
                    self.base_model,
                    self.personalized_model,
                    self.history_provider,
                )
                output_dict = result.to_dict()
            elif tool_name == "calculate_risk":
                risk_profile_str = arguments.get("risk_profile", state.request.risk_profile.value)
                try:
                    profile = RiskProfile(risk_profile_str)
                except ValueError as exc:
                    raise InvalidToolArgumentsError(tool_name, f"Invalid risk profile: {risk_profile_str}") from exc
                assert state.prediction is not None
                result = execute_calculate_risk(profile, state.prediction)
                output_dict = result.to_dict()
            elif tool_name == "optimize_block":
                risk_profile_str = arguments.get("risk_profile", state.request.risk_profile.value)
                try:
                    profile = RiskProfile(risk_profile_str)
                except ValueError as exc:
                    raise InvalidToolArgumentsError(tool_name, f"Invalid risk profile: {risk_profile_str}") from exc
                assert state.prediction is not None
                result = execute_optimize_block(
                    state.request.transaction,
                    state.prediction,
                    profile,
                    self.base_model,
                    self.personalized_model,
                    self.history_provider,
                    self.optimizer,
                )
                output_dict = result.to_dict()
            elif tool_name == "get_merchant_history":
                result = execute_get_merchant_history(arguments.get("merchant_id"))
                output_dict = result.to_dict()
            else:
                raise UnknownToolError(tool_name)
        except Exception as exc:
            completed_at = datetime.now(UTC)
            error_record = ToolAuditRecord(
                sequence=len(state.tool_calls) + 1,
                tool_name=tool_name,
                input_fingerprint_sha256=input_fingerprint,
                output_fingerprint_sha256="",
                arguments=arguments,
                result={},
                started_at=started_at,
                completed_at=completed_at,
                status="failed",
                error=str(exc),
            )
            raise

        completed_at = datetime.now(UTC)
        output_fingerprint = _compute_fingerprint(output_dict)
        audit_record = ToolAuditRecord(
            sequence=len(state.tool_calls) + 1,
            tool_name=tool_name,
            input_fingerprint_sha256=input_fingerprint,
            output_fingerprint_sha256=output_fingerprint,
            arguments=arguments,
            result=output_dict,
            started_at=started_at,
            completed_at=completed_at,
            status="succeeded",
            error=None,
        )
        return result, audit_record
