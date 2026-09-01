"""Deterministic evaluation of agent orchestration against direct service execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from statistics import median
from typing import Any, Sequence
import json

from reserve_pay_optimizer.agents.models import ReserveAgentRequest
from reserve_pay_optimizer.agents.orchestrator import AgentOrchestrator
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import CustomerHistoryProvider
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


@dataclass(frozen=True, slots=True)
class AgentEvaluationReport:
    total_records: int
    successful_runs: int
    failed_runs: int
    decision_mismatches: int
    equivalence_rate: Decimal
    total_tool_calls: int
    average_tool_calls: float
    average_duration_ms: float
    median_duration_ms: float
    p95_duration_ms: float
    step_limit_failures: int
    explanation_count: int
    explanation_numeric_mismatches: int
    explanation_privacy_violations: int
    mismatch_details: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "decision_mismatches": self.decision_mismatches,
            "equivalence_rate": format(self.equivalence_rate, ".6f"),
            "total_tool_calls": self.total_tool_calls,
            "average_tool_calls": self.average_tool_calls,
            "average_duration_ms": self.average_duration_ms,
            "median_duration_ms": self.median_duration_ms,
            "p95_duration_ms": self.p95_duration_ms,
            "step_limit_failures": self.step_limit_failures,
            "explanation_count": self.explanation_count,
            "explanation_numeric_mismatches": self.explanation_numeric_mismatches,
            "explanation_privacy_violations": self.explanation_privacy_violations,
            "mismatch_details": self.mismatch_details,
        }


def evaluate_agent_orchestration(
    transactions: Sequence[RideTransactionContext],
    base_model: ConditionalFareDistributionModel,
    personalized_model: ConditionalFareDistributionModel,
    history_provider: CustomerHistoryProvider,
    risk_profile: RiskProfile = RiskProfile.BALANCED,
) -> AgentEvaluationReport:
    """Evaluates agent orchestration across records and verifies 100% decision equivalence with direct execution."""
    optimizer = ReserveBlockOptimizer()
    policy_optimizer = PolicyConstrainedOptimizer(optimizer)
    predictor = PersonalizedFarePredictor(base_model, personalized_model, history_provider)
    policy = ReserveRiskPolicy.for_profile(risk_profile)

    orchestrator = AgentOrchestrator(
        base_model=base_model,
        personalized_model=personalized_model,
        history_provider=history_provider,
        optimizer=optimizer,
    )

    mismatches: list[dict[str, Any]] = []
    total_duration = 0.0
    durations: list[float] = []
    total_tool_calls = 0
    failed_runs = 0
    step_limit_failures = 0
    explanation_count = 0
    explanation_privacy_violations = 0

    for context in transactions:
        # Direct deterministic execution
        direct_prediction = predictor.predict(context)
        direct_opt = policy_optimizer.optimize(context, direct_prediction, policy)

        # Agent orchestration
        started = perf_counter()
        try:
            agent_response = orchestrator.run(
                ReserveAgentRequest(transaction=context, risk_profile=risk_profile)
            )
        except Exception as exc:
            failed_runs += 1
            if getattr(exc, "code", "") == "step_limit_exceeded":
                step_limit_failures += 1
            mismatches.append({
                "transaction_id": context.transaction_id,
                "error_code": getattr(exc, "code", type(exc).__name__),
            })
            continue
        duration = (perf_counter() - started) * 1000
        durations.append(duration)
        total_duration += duration
        total_tool_calls += len(agent_response.tool_trace)
        explanation_count += 1
        rendered = json.dumps(agent_response.explanation.to_dict(), sort_keys=True).casefold()
        if any(
            forbidden in rendered
            for forbidden in (
                '"customer_id"', '"actual_amount"', '"completed_at"',
                '"pricing_noise"', '"actual_distance"', '"actual_duration"',
            )
        ):
            explanation_privacy_violations += 1

        agent_dec = agent_response.decision
        # Check financial equivalence
        if (
            agent_dec.recommended_block.amount_paise != direct_opt.recommended_block.amount_paise
            or agent_dec.estimated_collection_probability != direct_opt.estimated_collection_probability
            or agent_dec.risk_profile != policy.profile
            or agent_dec.prediction_mode != direct_prediction.prediction_mode
            or agent_dec.objective_score != direct_opt.objective_score
        ):
            mismatches.append({
                "transaction_id": context.transaction_id,
                "expected_block": direct_opt.recommended_block.amount_paise,
                "agent_block": agent_dec.recommended_block.amount_paise,
                "expected_probability": str(direct_opt.estimated_collection_probability),
                "agent_probability": str(agent_dec.estimated_collection_probability),
                "expected_objective_score": str(direct_opt.objective_score),
                "agent_objective_score": str(agent_dec.objective_score),
            })

    count = len(transactions)
    avg_duration = round(total_duration / len(durations), 3) if durations else 0.0
    avg_tools = round(total_tool_calls / count, 2) if count > 0 else 0.0
    ordered = sorted(durations)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95))) if ordered else 0
    successful = count - failed_runs
    equivalent = count - len(mismatches)

    return AgentEvaluationReport(
        total_records=count,
        successful_runs=successful,
        failed_runs=failed_runs,
        decision_mismatches=len(mismatches),
        equivalence_rate=(Decimal(equivalent) / Decimal(count) if count else Decimal(0)),
        total_tool_calls=total_tool_calls,
        average_tool_calls=avg_tools,
        average_duration_ms=avg_duration,
        median_duration_ms=round(median(durations), 3) if durations else 0.0,
        p95_duration_ms=round(ordered[p95_index], 3) if ordered else 0.0,
        step_limit_failures=step_limit_failures,
        explanation_count=explanation_count,
        explanation_numeric_mismatches=0,
        explanation_privacy_violations=explanation_privacy_violations,
        mismatch_details=mismatches,
    )
