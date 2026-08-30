"""Deterministic evaluation of agent orchestration against direct service execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any, Sequence

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
    decision_mismatches: int
    average_tool_calls: float
    average_duration_ms: float
    mismatch_details: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "successful_runs": self.successful_runs,
            "decision_mismatches": self.decision_mismatches,
            "average_tool_calls": self.average_tool_calls,
            "average_duration_ms": self.average_duration_ms,
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
    total_tool_calls = 0

    for context in transactions:
        # Direct deterministic execution
        direct_prediction = predictor.predict(context)
        direct_opt = policy_optimizer.optimize(context, direct_prediction, policy)

        # Agent orchestration
        started = perf_counter()
        agent_response = orchestrator.run(
            ReserveAgentRequest(transaction=context, risk_profile=risk_profile)
        )
        duration = (perf_counter() - started) * 1000
        total_duration += duration
        total_tool_calls += len(agent_response.tool_trace)

        agent_dec = agent_response.decision
        # Check financial equivalence
        if (
            agent_dec.recommended_block.amount_paise != direct_opt.recommended_block.amount_paise
            or agent_dec.estimated_collection_probability != direct_opt.estimated_collection_probability
            or agent_dec.risk_profile != policy.profile
            or agent_dec.prediction_mode != direct_prediction.prediction_mode
        ):
            mismatches.append({
                "transaction_id": context.transaction_id,
                "expected_block": direct_opt.recommended_block.amount_paise,
                "agent_block": agent_dec.recommended_block.amount_paise,
                "expected_probability": str(direct_opt.estimated_collection_probability),
                "agent_probability": str(agent_dec.estimated_collection_probability),
            })

    count = len(transactions)
    avg_duration = round(total_duration / count, 3) if count > 0 else 0.0
    avg_tools = round(total_tool_calls / count, 2) if count > 0 else 0.0

    return AgentEvaluationReport(
        total_records=count,
        successful_runs=count - len(mismatches),
        decision_mismatches=len(mismatches),
        average_tool_calls=avg_tools,
        average_duration_ms=avg_duration,
        mismatch_details=mismatches,
    )
