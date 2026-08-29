"""Typed authoritative evidence for static and dynamic explanations."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.optimization.models import ScoreComponents
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy
from reserve_pay_optimizer.prediction.config import quantile_key

EXPLANATION_VERSION = "reserve_decision_explanation_v1"


class DecisionType(StrEnum):
    INITIAL_RESERVE = "initial_reserve"
    DYNAMIC_REOPTIMIZATION = "dynamic_reoptimization"


class ExplanationLevel(StrEnum):
    CONCISE = "concise"
    DETAILED = "detailed"


class FactorDirection(StrEnum):
    HIGHER_BLOCK = "higher_block"
    LOWER_BLOCK = "lower_block"
    CONTEXT = "context"
    TRADEOFF = "tradeoff"


class ExplanationFactorCode(StrEnum):
    BASE_ESTIMATE = "base_estimate"
    PREDICTED_UNCERTAINTY = "predicted_uncertainty"
    MERCHANT_RISK_POLICY = "merchant_risk_policy"
    CUSTOMER_HISTORY = "customer_history"
    COLD_START = "cold_start"
    SURGE = "surge"
    DISTANCE = "distance"
    DURATION = "duration"
    TIME_CONTEXT = "time_context"
    OPTIMIZATION_TRADEOFF = "optimization_tradeoff"
    DYNAMIC_TRAFFIC_CHANGE = "dynamic_traffic_change"
    DYNAMIC_ROUTE_CHANGE = "dynamic_route_change"
    DYNAMIC_SURGE_CHANGE = "dynamic_surge_change"
    DYNAMIC_FARE_ESTIMATE_CHANGE = "dynamic_fare_estimate_change"


class AuthorizationStatus(StrEnum):
    RECOMMENDATION_ONLY = "recommendation_only"
    SIMULATED_CONFIRMED = "simulated_confirmed"


@dataclass(frozen=True, slots=True)
class ExplanationFactor:
    code: ExplanationFactorCode
    label: str
    direction: FactorDirection
    evidence: tuple[tuple[str, str | int | bool], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "label": self.label,
            "direction": self.direction.value,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class HistorySummary:
    completed_ride_count: int
    mean_fare_ratio: Decimal
    fare_ratio_stddev: Decimal
    overrun_rate: Decimal
    mean_positive_overrun_ratio: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "completed_ride_count": self.completed_ride_count,
            "mean_fare_ratio": format_ratio(self.mean_fare_ratio),
            "fare_ratio_stddev": format_ratio(self.fare_ratio_stddev),
            "overrun_rate": format_ratio(self.overrun_rate),
            "mean_positive_overrun_ratio": format_ratio(
                self.mean_positive_overrun_ratio
            ),
        }


@dataclass(frozen=True, slots=True)
class PredictionSummary:
    quantiles: tuple[tuple[Decimal, Money], ...]

    def to_dict(self) -> dict[str, int]:
        return {
            quantile_key(probability): amount.amount_paise
            for probability, amount in self.quantiles
        }


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    block_amount: Money
    estimated_collection_probability: Decimal
    objective_score: Decimal
    selected: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "block_amount_paise": self.block_amount.amount_paise,
            "estimated_collection_probability": format_ratio(
                self.estimated_collection_probability
            ),
            "objective_score": format_ratio(self.objective_score),
            "selected": self.selected,
        }


@dataclass(frozen=True, slots=True)
class TradeoffSummary:
    minimum_feasible_probability: Decimal
    selected_probability_exceeds_minimum: bool
    profile_quantile_amount: Money
    selected_block_exceeds_profile_quantile: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "minimum_feasible_probability": format_ratio(
                self.minimum_feasible_probability
            ),
            "selected_probability_exceeds_minimum": self.selected_probability_exceeds_minimum,
            "profile_quantile_amount_paise": self.profile_quantile_amount.amount_paise,
            "selected_block_exceeds_profile_quantile": self.selected_block_exceeds_profile_quantile,
        }


@dataclass(frozen=True, slots=True)
class DynamicFieldChange:
    field: str
    previous_value: str | int
    revised_value: str | int

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "previous_value": self.previous_value,
            "revised_value": self.revised_value,
        }


@dataclass(frozen=True, slots=True)
class DynamicContextEvidence:
    event_id: str
    sequence_number: int
    session_version: int
    update_reason: str
    previous_authorized_block: Money
    previous_target_block: Money
    recommended_target_block: Money
    additional_block_required: Money
    current_block_sufficient: bool
    authorization_status: AuthorizationStatus
    changed_fields: tuple[DynamicFieldChange, ...]
    previous_quantiles: PredictionSummary
    revised_quantiles: PredictionSummary

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "sequence_number": self.sequence_number,
            "session_version": self.session_version,
            "update_reason": self.update_reason,
            "previous_authorized_block_paise": self.previous_authorized_block.amount_paise,
            "previous_target_block_paise": self.previous_target_block.amount_paise,
            "recommended_target_block_paise": self.recommended_target_block.amount_paise,
            "additional_block_required_paise": self.additional_block_required.amount_paise,
            "current_block_sufficient": self.current_block_sufficient,
            "authorization_status": self.authorization_status.value,
            "additional_block_formula": "max(recommended_target_block - current_authorized_block, 0)",
            "changed_fields": [item.to_dict() for item in self.changed_fields],
            "previous_quantiles": self.previous_quantiles.to_dict(),
            "revised_quantiles": self.revised_quantiles.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    transaction_id: str
    decision_type: DecisionType
    recommended_block: Money
    estimated_amount: Money
    risk_policy: ReserveRiskPolicy
    estimated_collection_probability: Decimal
    expected_excess_block: Money
    expected_excess_ratio: Decimal
    friction_ratio: Decimal
    objective_score: Decimal
    objective_components: ScoreComponents
    optimization_config: tuple[tuple[str, str], ...]
    prediction_mode: str
    model_version: str
    history_summary: HistorySummary | None
    prediction_summary: PredictionSummary
    decision_factors: tuple[ExplanationFactor, ...]
    tradeoff_summary: TradeoffSummary
    candidate_comparison: tuple[CandidateComparison, ...]
    dynamic_context: DynamicContextEvidence | None = None
    explanation_version: str = EXPLANATION_VERSION

    def facts_dict(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "explanation_version": self.explanation_version,
            "decision_type": self.decision_type.value,
            "currency": "INR",
            "recommended_block_paise": self.recommended_block.amount_paise,
            "estimated_amount_paise": self.estimated_amount.amount_paise,
            "risk_policy": {
                "profile": self.risk_policy.profile.value,
                "target_collection_probability": format_ratio(
                    self.risk_policy.target_collection_probability
                ),
            },
            "estimated_collection_probability": format_ratio(
                self.estimated_collection_probability
            ),
            "expected_excess_block_paise": self.expected_excess_block.amount_paise,
            "expected_excess_ratio": format_ratio(self.expected_excess_ratio),
            "friction_ratio": format_ratio(self.friction_ratio),
            "objective_score": format_ratio(self.objective_score),
            "objective_components": self.objective_components.to_dict(),
            "optimization_config": dict(self.optimization_config),
            "prediction_mode": self.prediction_mode,
            "model_version": self.model_version,
            "history_summary": (
                self.history_summary.to_dict() if self.history_summary else None
            ),
            "prediction_quantiles_paise": self.prediction_summary.to_dict(),
            "decision_factors": [factor.to_dict() for factor in self.decision_factors],
            "tradeoff_summary": self.tradeoff_summary.to_dict(),
            "candidate_comparison": [item.to_dict() for item in self.candidate_comparison],
            "dynamic_context": (
                self.dynamic_context.to_dict() if self.dynamic_context else None
            ),
        }

    @property
    def explanation_id(self) -> str:
        canonical = json.dumps(
            self.facts_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {"explanation_id": self.explanation_id, **self.facts_dict()}


@dataclass(frozen=True, slots=True)
class RenderedDecisionExplanation:
    facts: DecisionExplanation
    text: str
    detail: ExplanationLevel
    renderer_type: str
    fallback_used: bool = False
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "facts": self.facts.to_dict(),
            "text": self.text,
            "detail": self.detail.value,
            "renderer_type": self.renderer_type,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
        }
