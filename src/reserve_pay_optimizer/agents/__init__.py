"""Phase-12 AI Agent Layer for Reserve Pay Block Optimizer."""

from __future__ import annotations

from reserve_pay_optimizer.agents.deterministic_model import DeterministicAgentModel
from reserve_pay_optimizer.agents.errors import (
    AgentError,
    DecisionConsistencyError,
    InvalidAgentResponseError,
    InvalidToolArgumentsError,
    StepLimitExceededError,
    ToolExecutionError,
    ToolOrderError,
    UnknownToolError,
)
from reserve_pay_optimizer.agents.evaluation import (
    AgentEvaluationReport,
    evaluate_agent_orchestration,
)
from reserve_pay_optimizer.agents.explanation_agent import ExplanationAgent
from reserve_pay_optimizer.agents.models import (
    AgentOperationalMetrics,
    AgentResponse,
    AgentStateStatus,
    CustomerHistoryToolOutput,
    ExplanationAgentResult,
    MerchantHistoryToolOutput,
    OptimizationToolOutput,
    PredictionToolOutput,
    ReasonCode,
    ReserveAgentDecision,
    ReserveAgentRequest,
    ReserveAgentState,
    RiskLevel,
    RiskToolOutput,
    ToolAuditRecord,
)
from reserve_pay_optimizer.agents.orchestrator import AgentOrchestrator
from reserve_pay_optimizer.agents.protocol import (
    AgentActionType,
    AgentModel,
    AgentModelAction,
)
from reserve_pay_optimizer.agents.registry import AgentToolRegistry
from reserve_pay_optimizer.agents.reserve_agent import ReserveIntelligenceAgent

__all__ = [
    "AgentActionType",
    "AgentError",
    "AgentEvaluationReport",
    "AgentModel",
    "AgentModelAction",
    "AgentOperationalMetrics",
    "AgentOrchestrator",
    "AgentResponse",
    "AgentStateStatus",
    "AgentToolRegistry",
    "CustomerHistoryToolOutput",
    "DecisionConsistencyError",
    "DeterministicAgentModel",
    "ExplanationAgent",
    "ExplanationAgentResult",
    "InvalidAgentResponseError",
    "InvalidToolArgumentsError",
    "MerchantHistoryToolOutput",
    "OptimizationToolOutput",
    "PredictionToolOutput",
    "ReasonCode",
    "ReserveAgentDecision",
    "ReserveAgentRequest",
    "ReserveAgentState",
    "ReserveIntelligenceAgent",
    "RiskLevel",
    "RiskToolOutput",
    "StepLimitExceededError",
    "ToolAuditRecord",
    "ToolExecutionError",
    "ToolOrderError",
    "UnknownToolError",
    "evaluate_agent_orchestration",
]
