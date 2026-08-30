"""Typed domain and orchestration models for the Phase-12 AI Agent layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.policy.risk import RiskProfile


class AgentStateStatus(StrEnum):
    PENDING = "pending"
    GATHERING_HISTORY = "gathering_history"
    PREDICTING = "predicting"
    ASSESSING_RISK = "assessing_risk"
    OPTIMIZING = "optimizing"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReasonCode(StrEnum):
    POLICY_AND_UNCERTAINTY = "POLICY_AND_UNCERTAINTY"
    PERSONALIZED_OVERRUN_HISTORY = "PERSONALIZED_OVERRUN_HISTORY"
    PERSONALIZED_STABLE_HISTORY = "PERSONALIZED_STABLE_HISTORY"
    COLD_START_BASE_MODEL = "COLD_START_BASE_MODEL"
    DYNAMIC_CONDITIONS_CHANGED = "DYNAMIC_CONDITIONS_CHANGED"


@dataclass(frozen=True, slots=True)
class CustomerHistoryToolOutput:
    customer_id: str
    history_count: int
    mean_fare_ratio: Decimal | None
    fare_ratio_stddev: Decimal | None
    overrun_rate: Decimal | None
    mean_positive_overrun_ratio: Decimal | None
    personalization_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "history_count": self.history_count,
            "mean_fare_ratio": str(self.mean_fare_ratio) if self.mean_fare_ratio is not None else None,
            "fare_ratio_stddev": str(self.fare_ratio_stddev) if self.fare_ratio_stddev is not None else None,
            "overrun_rate": str(self.overrun_rate) if self.overrun_rate is not None else None,
            "mean_positive_overrun_ratio": str(self.mean_positive_overrun_ratio) if self.mean_positive_overrun_ratio is not None else None,
            "personalization_eligible": self.personalization_eligible,
        }


@dataclass(frozen=True, slots=True)
class PredictionToolOutput:
    prediction_mode: str
    history_count: int
    model_version: str
    quantiles_paise: dict[str, int]
    lower_interval_paise: int
    upper_interval_paise: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_mode": self.prediction_mode,
            "history_count": self.history_count,
            "model_version": self.model_version,
            "quantiles_paise": self.quantiles_paise,
            "modeled_range": {
                "lower_amount_paise": self.lower_interval_paise,
                "upper_amount_paise": self.upper_interval_paise,
                "label": "Modeled Q05–Q95 interval",
            },
        }


@dataclass(frozen=True, slots=True)
class RiskToolOutput:
    risk_profile: str
    target_collection_probability: Decimal
    risk_level: RiskLevel
    risk_basis: str
    maximum_modeled_probability: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_profile": self.risk_profile,
            "target_collection_probability": str(self.target_collection_probability),
            "risk_level": self.risk_level.value,
            "risk_basis": self.risk_basis,
            "maximum_modeled_probability": str(self.maximum_modeled_probability),
        }


@dataclass(frozen=True, slots=True)
class OptimizationToolOutput:
    recommended_block: Money
    estimated_collection_probability: Decimal
    estimated_under_block_probability: Decimal
    expected_excess_block: Money
    objective_score: Decimal
    objective_components: dict[str, Decimal]
    candidate_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_block_paise": self.recommended_block.amount_paise,
            "estimated_collection_probability": str(self.estimated_collection_probability),
            "estimated_under_block_probability": str(self.estimated_under_block_probability),
            "expected_excess_block_paise": self.expected_excess_block.amount_paise,
            "objective_score": str(self.objective_score),
            "objective_components": {
                key: str(value) for key, value in self.objective_components.items()
            },
            "candidate_count": self.candidate_count,
        }


@dataclass(frozen=True, slots=True)
class MerchantHistoryToolOutput:
    status: str = "unavailable"
    reason: str = "Merchant-history subsystem is not implemented."

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ToolAuditRecord:
    sequence: int
    tool_name: str
    input_fingerprint_sha256: str
    output_fingerprint_sha256: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    started_at: datetime
    completed_at: datetime
    status: str = "succeeded"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "tool_name": self.tool_name,
            "input_fingerprint_sha256": self.input_fingerprint_sha256,
            "output_fingerprint_sha256": self.output_fingerprint_sha256,
            "arguments": self.arguments,
            "result": self.result,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class ReserveAgentRequest:
    transaction: RideTransactionContext
    risk_profile: RiskProfile = RiskProfile.BALANCED
    customer_history_profile: str | None = None
    agent_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReserveAgentDecision:
    transaction_id: str
    agent_run_id: str
    recommended_block: Money
    estimated_collection_probability: Decimal
    estimated_under_block_probability: Decimal
    risk_profile: RiskProfile
    risk: RiskLevel
    prediction_mode: str
    history_count: int
    model_version: str
    objective_score: Decimal
    reason_code: ReasonCode
    reason: str
    confidence: Decimal
    merchant_history_available: bool = False
    merchant_history: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "agent_run_id": self.agent_run_id,
            "recommended_block_paise": self.recommended_block.amount_paise,
            "estimated_collection_probability": str(self.estimated_collection_probability),
            "estimated_under_block_probability": str(self.estimated_under_block_probability),
            "risk_profile": self.risk_profile.value,
            "risk": self.risk.value,
            "prediction_mode": self.prediction_mode,
            "history_count": self.history_count,
            "model_version": self.model_version,
            "objective_score": str(self.objective_score),
            "reason_code": self.reason_code.value,
            "reason": self.reason,
            "confidence": str(self.confidence),
            "merchant_history_available": self.merchant_history_available,
            "merchant_history": self.merchant_history,
        }


@dataclass(slots=True)
class ReserveAgentState:
    request: ReserveAgentRequest
    agent_run_id: str
    status: AgentStateStatus = AgentStateStatus.PENDING
    step_count: int = 0
    customer_history: CustomerHistoryToolOutput | None = None
    prediction: PredictionToolOutput | None = None
    risk_assessment: RiskToolOutput | None = None
    optimization: OptimizationToolOutput | None = None
    merchant_history: MerchantHistoryToolOutput | None = None
    tool_calls: list[ToolAuditRecord] = field(default_factory=list)
    decision: ReserveAgentDecision | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExplanationAgentResult:
    transaction_id: str
    agent_run_id: str
    explanation_id: str
    summary: str
    details: str
    factors: list[dict[str, Any]]
    confidence_note: str
    renderer: str = "deterministic_phase_9"

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "agent_run_id": self.agent_run_id,
            "explanation_id": self.explanation_id,
            "summary": self.summary,
            "details": self.details,
            "factors": self.factors,
            "confidence_note": self.confidence_note,
            "renderer": self.renderer,
        }


@dataclass(frozen=True, slots=True)
class AgentResponse:
    run_id: str
    decision: ReserveAgentDecision
    explanation: ExplanationAgentResult
    tool_trace: list[ToolAuditRecord]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision": self.decision.to_dict(),
            "explanation": self.explanation.to_dict(),
            "tool_trace": [record.to_dict() for record in self.tool_trace],
            "metrics": self.metrics,
        }


@dataclass(frozen=True, slots=True)
class AgentOperationalMetrics:
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_tool_calls: int = 0
    step_limit_failures: int = 0
    explanation_fallbacks: int = 0

    @property
    def average_tool_calls(self) -> float:
        if self.successful_runs == 0:
            return 0.0
        return round(self.total_tool_calls / self.successful_runs, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "total_tool_calls": self.total_tool_calls,
            "average_tool_calls": self.average_tool_calls,
            "step_limit_failures": self.step_limit_failures,
            "explanation_fallbacks": self.explanation_fallbacks,
        }
