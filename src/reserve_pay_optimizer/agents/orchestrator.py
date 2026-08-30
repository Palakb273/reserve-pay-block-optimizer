"""High-level agent orchestrator combining Reserve Intelligence Agent and Explanation Agent."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from reserve_pay_optimizer.agents.errors import AgentError
from reserve_pay_optimizer.agents.explanation_agent import ExplanationAgent
from reserve_pay_optimizer.agents.models import (
    AgentOperationalMetrics,
    AgentResponse,
    ReserveAgentRequest,
)
from reserve_pay_optimizer.agents.protocol import AgentModel
from reserve_pay_optimizer.agents.registry import AgentToolRegistry
from reserve_pay_optimizer.agents.reserve_agent import ReserveIntelligenceAgent
from reserve_pay_optimizer.explainability.service import ExplanationService
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import CustomerHistoryProvider
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


class AgentOrchestrator:
    """Orchestrates multi-agent execution pipeline and tracks operational metrics."""

    def __init__(
        self,
        base_model: ConditionalFareDistributionModel,
        personalized_model: ConditionalFareDistributionModel,
        history_provider: CustomerHistoryProvider,
        optimizer: ReserveBlockOptimizer | None = None,
        explanation_service: ExplanationService | None = None,
        model: AgentModel | None = None,
        max_steps: int = ReserveIntelligenceAgent.DEFAULT_MAX_STEPS,
    ) -> None:
        self.base_model = base_model
        self.personalized_model = personalized_model
        self.history_provider = history_provider
        self.optimizer = optimizer or ReserveBlockOptimizer()
        self.explanation_service = explanation_service or ExplanationService()
        
        self.registry = AgentToolRegistry(
            base_model=self.base_model,
            personalized_model=self.personalized_model,
            history_provider=self.history_provider,
            optimizer=self.optimizer,
        )
        self.reserve_agent = ReserveIntelligenceAgent(
            registry=self.registry,
            model=model,
            max_steps=max_steps,
        )
        self.explanation_agent = ExplanationAgent(
            base_model=self.base_model,
            personalized_model=self.personalized_model,
            history_provider=self.history_provider,
            explanation_service=self.explanation_service,
        )
        
        self._total_runs = 0
        self._successful_runs = 0
        self._failed_runs = 0
        self._total_tool_calls = 0
        self._step_limit_failures = 0
        self._explanation_fallbacks = 0

    @property
    def metrics(self) -> AgentOperationalMetrics:
        return AgentOperationalMetrics(
            total_runs=self._total_runs,
            successful_runs=self._successful_runs,
            failed_runs=self._failed_runs,
            total_tool_calls=self._total_tool_calls,
            step_limit_failures=self._step_limit_failures,
            explanation_fallbacks=self._explanation_fallbacks,
        )

    def run(self, request: ReserveAgentRequest) -> AgentResponse:
        """Executes the full agent workflow: Reserve Agent -> Explanation Agent."""
        started = perf_counter()
        self._total_runs += 1
        
        try:
            agent_state = self.reserve_agent.decide(request)
            self._total_tool_calls += len(agent_state.tool_calls)
            assert agent_state.decision is not None
            decision = agent_state.decision
        except Exception as exc:
            self._failed_runs += 1
            if "Step limit exceeded" in str(exc):
                self._step_limit_failures += 1
            raise

        try:
            explanation = self.explanation_agent.explain(request.transaction, decision)
        except Exception:
            self._explanation_fallbacks += 1
            raise

        self._successful_runs += 1
        duration_ms = round((perf_counter() - started) * 1000, 3)

        return AgentResponse(
            run_id=agent_state.agent_run_id,
            decision=decision,
            explanation=explanation,
            tool_trace=agent_state.tool_calls,
            metrics={
                "processing_ms": duration_ms,
                "step_count": agent_state.step_count,
                "tool_call_count": len(agent_state.tool_calls),
                "financial_logic_location": "python_backend",
            },
        )
