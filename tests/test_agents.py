"""Comprehensive unit and integration tests for the Phase-12 AI Agent layer."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from reserve_pay_optimizer.agents.deterministic_model import DeterministicAgentModel
from reserve_pay_optimizer.agents.errors import (
    DecisionConsistencyError,
    InvalidToolArgumentsError,
    StepLimitExceededError,
    ToolOrderError,
    UnknownToolError,
)
from reserve_pay_optimizer.agents.evaluation import evaluate_agent_orchestration
from reserve_pay_optimizer.agents.explanation_agent import ExplanationAgent
from reserve_pay_optimizer.agents.models import (
    ReasonCode,
    ReserveAgentDecision,
    ReserveAgentRequest,
    ReserveAgentState,
    RiskLevel,
)
from reserve_pay_optimizer.agents.orchestrator import AgentOrchestrator
from reserve_pay_optimizer.agents.protocol import (
    AgentActionType,
    AgentModel,
    AgentModelAction,
)
from reserve_pay_optimizer.agents.registry import AgentToolRegistry
from reserve_pay_optimizer.agents.reserve_agent import ReserveIntelligenceAgent
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import InMemoryCustomerHistoryProvider
from reserve_pay_optimizer.personalization.persistence import load_personalized_artifact
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.persistence import load_predictor_artifact
from reserve_pay_optimizer.web.app import create_app
from reserve_pay_optimizer.web.evidence import prepare_dashboard_evidence
from reserve_pay_optimizer.web.schemas import OptimizeRequest
from reserve_pay_optimizer.web.services import DashboardSettings


ROOT = Path(__file__).resolve().parents[1]


class AgentLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_artifact = load_predictor_artifact(
            ROOT / "artifacts/prediction/fare_distribution_v1"
        )
        cls.personalized_artifact = load_personalized_artifact(
            ROOT / "artifacts/prediction/fare_distribution_personalized_v1"
        )

        # Build sample completed customer history for tests
        cls.now = datetime(2027, 1, 15, 18, 30, tzinfo=UTC)
        cls.completed_contexts: list[RideTransactionContext] = []
        cls.completed_outcomes: list[RideTransactionOutcome] = []

        for index in range(1, 9):
            ride_time = datetime(2027, 1, index, 10, 0, tzinfo=UTC)
            comp_time = datetime(2027, 1, index, 10, 35, tzinfo=UTC)
            ctx = RideTransactionContext(
                transaction_id=f"HIST-TX-{index}",
                customer_id="CUST-STABLE",
                estimated_amount=Money(60000),
                city=SupportedCity.HYDERABAD,
                distance_km=Decimal("15.0"),
                estimated_duration_minutes=30,
                surge_multiplier=Decimal("1.00"),
                timestamp=ride_time,
            )
            out = RideTransactionOutcome(
                transaction_id=f"HIST-TX-{index}",
                actual_amount=Money(62000),
                completed_at=comp_time,
            )
            cls.completed_contexts.append(ctx)
            cls.completed_outcomes.append(out)

        cls.history_provider = InMemoryCustomerHistoryProvider(
            cls.completed_contexts, cls.completed_outcomes
        )

    def _sample_context(
        self,
        customer_id: str = "CUST-STABLE",
        transaction_id: str = "AGENT-TX-001",
    ) -> RideTransactionContext:
        return RideTransactionContext(
            transaction_id=transaction_id,
            customer_id=customer_id,
            estimated_amount=Money(65000),
            city=SupportedCity.HYDERABAD,
            distance_km=Decimal("18.4"),
            estimated_duration_minutes=42,
            surge_multiplier=Decimal("1.18"),
            timestamp=self.now,
        )

    def test_tool_registry_allowlist_and_unknown_tool_rejection(self) -> None:
        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        self.assertIn("get_customer_history", registry.available_tools)
        self.assertIn("get_transaction_prediction", registry.available_tools)
        self.assertIn("calculate_risk", registry.available_tools)
        self.assertIn("optimize_block", registry.available_tools)
        self.assertIn("get_merchant_history", registry.available_tools)

        req = ReserveAgentRequest(transaction=self._sample_context())
        state = ReserveAgentState(request=req, agent_run_id="RUN-TEST-001")

        with self.assertRaises(UnknownToolError):
            registry.execute_tool("arbitrary_python_eval", {}, state)

        with self.assertRaises(UnknownToolError):
            registry.execute_tool("debit_reserve_funds", {}, state)

    def test_tool_order_dependencies_enforced(self) -> None:
        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        req = ReserveAgentRequest(transaction=self._sample_context())
        state = ReserveAgentState(request=req, agent_run_id="RUN-TEST-002")

        # Cannot predict before customer history
        with self.assertRaises(ToolOrderError) as ctx:
            registry.execute_tool("get_transaction_prediction", {}, state)
        self.assertEqual(ctx.exception.details["missing_dependency"], "get_customer_history")

        # Cannot optimize before prediction
        with self.assertRaises(ToolOrderError) as ctx:
            registry.execute_tool("optimize_block", {"risk_profile": "balanced"}, state)
        self.assertEqual(ctx.exception.details["missing_dependency"], "get_transaction_prediction")

    def test_customer_history_tool_no_leakage(self) -> None:
        context = self._sample_context()
        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        state = ReserveAgentState(
            request=ReserveAgentRequest(transaction=context),
            agent_run_id="RUN-TEST-003",
        )
        result, audit = registry.execute_tool("get_customer_history", {}, state)
        self.assertEqual(result.history_count, 8)
        self.assertTrue(result.personalization_eligible)
        self.assertTrue(audit.input_fingerprint_sha256)
        self.assertTrue(audit.output_fingerprint_sha256)
        self.assertEqual(audit.status, "succeeded")

    def test_failed_tool_execution_is_retained_in_the_audit_trace(self) -> None:
        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        state = ReserveAgentState(
            request=ReserveAgentRequest(transaction=self._sample_context()),
            agent_run_id="RUN-FAIL-TRACE",
        )
        with patch(
            "reserve_pay_optimizer.agents.registry.execute_get_customer_history",
            side_effect=RuntimeError("sensitive provider detail"),
        ), self.assertRaises(RuntimeError):
            registry.execute_tool("get_customer_history", {}, state)
        self.assertEqual(len(state.tool_calls), 1)
        self.assertEqual(state.tool_calls[0].status, "failed")
        self.assertEqual(state.tool_calls[0].error, "RuntimeError")
        self.assertNotIn("sensitive", str(state.tool_calls[0].to_dict()))

    def test_prediction_tool_cold_start_vs_personalized(self) -> None:
        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )

        # Cold start customer
        cold_context = self._sample_context(customer_id="CUST-NEW-001")
        state_cold = ReserveAgentState(
            request=ReserveAgentRequest(transaction=cold_context),
            agent_run_id="RUN-COLD",
        )
        res_hist, _ = registry.execute_tool("get_customer_history", {}, state_cold)
        state_cold.customer_history = res_hist
        pred_cold, _ = registry.execute_tool("get_transaction_prediction", {}, state_cold)
        self.assertEqual(pred_cold.prediction_mode, "base")
        self.assertEqual(pred_cold.history_count, 0)

        # Personalized customer
        state_pers = ReserveAgentState(
            request=ReserveAgentRequest(transaction=self._sample_context()),
            agent_run_id="RUN-PERS",
        )
        res_hist_p, _ = registry.execute_tool("get_customer_history", {}, state_pers)
        state_pers.customer_history = res_hist_p
        pred_pers, _ = registry.execute_tool("get_transaction_prediction", {}, state_pers)
        self.assertEqual(pred_pers.prediction_mode, "personalized")
        self.assertEqual(pred_pers.history_count, 8)
        self.assertIn("0.97", pred_pers.quantiles_paise)

    def test_merchant_history_returns_unavailable_honestly(self) -> None:
        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        state = ReserveAgentState(
            request=ReserveAgentRequest(transaction=self._sample_context()),
            agent_run_id="RUN-MERCHANT",
        )
        result, audit = registry.execute_tool("get_merchant_history", {}, state)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("not implemented", result.reason)

    def test_direct_execution_equals_agent_orchestration(self) -> None:
        context = self._sample_context()
        policy = RiskProfile.BALANCED

        # Direct execution
        predictor = PersonalizedFarePredictor(
            self.base_artifact.model,
            self.personalized_artifact.model,
            self.history_provider,
        )
        direct_pred = predictor.predict(context)
        direct_opt = PolicyConstrainedOptimizer(ReserveBlockOptimizer()).optimize(
            context, direct_pred, ReserveRiskPolicy.for_profile(policy)
        )

        # Agent orchestration
        orchestrator = AgentOrchestrator(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        agent_response = orchestrator.run(
            ReserveAgentRequest(transaction=context, risk_profile=policy)
        )

        # 100% Financial Equivalence Check
        agent_dec = agent_response.decision
        self.assertEqual(
            agent_dec.recommended_block.amount_paise,
            direct_opt.recommended_block.amount_paise,
        )
        self.assertEqual(
            agent_dec.estimated_collection_probability,
            direct_opt.estimated_collection_probability,
        )
        self.assertEqual(agent_dec.risk_profile, policy)
        self.assertEqual(agent_dec.prediction_mode, direct_pred.prediction_mode)
        self.assertEqual(agent_dec.objective_score, direct_opt.objective_score)
        self.assertEqual(len(agent_response.tool_trace), 4)
        serialized = agent_response.to_dict()["decision"]
        for field in (
            "estimated_collection_probability",
            "estimated_under_block_probability",
            "objective_score",
            "confidence",
        ):
            self.assertRegex(serialized[field], r"^-?\d+\.\d{6}$")

        # Verify tool trace sequence
        trace_tools = [item.tool_name for item in agent_response.tool_trace]
        self.assertEqual(trace_tools, [
            "get_customer_history",
            "get_transaction_prediction",
            "calculate_risk",
            "optimize_block",
        ])

    def test_explanation_agent_matches_decision_and_explains(self) -> None:
        context = self._sample_context()
        orchestrator = AgentOrchestrator(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        response = orchestrator.run(ReserveAgentRequest(transaction=context))
        explanation = response.explanation
        self.assertEqual(explanation.transaction_id, context.transaction_id)
        self.assertTrue(explanation.summary)
        self.assertTrue(explanation.details)
        self.assertTrue(explanation.factors)
        self.assertIn("Modeled collection coverage", explanation.confidence_note)

    def test_cold_start_reason_uses_shared_minimum_history(self) -> None:
        orchestrator = AgentOrchestrator(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        response = orchestrator.run(ReserveAgentRequest(
            transaction=self._sample_context(customer_id="CUST-NO-HISTORY")
        ))
        self.assertEqual(response.decision.prediction_mode, "base")
        self.assertIn("minimum of 3 rides", response.decision.reason)

    def test_decision_consistency_violation_raises(self) -> None:
        # A malicious or broken model trying to return a fabricated block
        class MaliciousAgentModel(AgentModel):
            def next_action(self, state: ReserveAgentState, available_tools: list[str]) -> AgentModelAction:
                if state.customer_history is None:
                    return AgentModelAction(action_type=AgentActionType.CALL_TOOL, tool_name="get_customer_history")
                if state.prediction is None:
                    return AgentModelAction(action_type=AgentActionType.CALL_TOOL, tool_name="get_transaction_prediction")
                if state.risk_assessment is None:
                    return AgentModelAction(action_type=AgentActionType.CALL_TOOL, tool_name="calculate_risk")
                if state.optimization is None:
                    return AgentModelAction(action_type=AgentActionType.CALL_TOOL, tool_name="optimize_block")
                
                # Try to finalize with a fabricated block of 99999 paise
                fake_decision = ReserveAgentDecision(
                    transaction_id=state.request.transaction.transaction_id,
                    agent_run_id=state.agent_run_id,
                    recommended_block=Money(99999),
                    estimated_collection_probability=Decimal("0.970000"),
                    estimated_under_block_probability=Decimal("0.030000"),
                    risk_profile=RiskProfile.BALANCED,
                    risk=RiskLevel.LOW,
                    prediction_mode="personalized",
                    history_count=8,
                    model_version="test",
                    objective_score=Decimal("0.100000"),
                    reason_code=ReasonCode.POLICY_AND_UNCERTAINTY,
                    reason="Fabricated decision",
                    confidence=Decimal("0.970000"),
                )
                return AgentModelAction(action_type=AgentActionType.FINALIZE, final_decision=fake_decision)

        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        agent = ReserveIntelligenceAgent(registry=registry, model=MaliciousAgentModel())
        with self.assertRaises(DecisionConsistencyError):
            agent.decide(ReserveAgentRequest(transaction=self._sample_context()))

    def test_step_limit_terminates_infinite_loop(self) -> None:
        # Loop model calling get_customer_history repeatedly
        class InfiniteLoopModel(AgentModel):
            def next_action(self, state: ReserveAgentState, available_tools: list[str]) -> AgentModelAction:
                return AgentModelAction(action_type=AgentActionType.CALL_TOOL, tool_name="get_customer_history")

        registry = AgentToolRegistry(
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
        )
        agent = ReserveIntelligenceAgent(registry=registry, model=InfiniteLoopModel(), max_steps=4)
        with self.assertRaises(StepLimitExceededError) as ctx:
            agent.decide(ReserveAgentRequest(transaction=self._sample_context()))
        self.assertEqual(ctx.exception.details["max_steps"], 4)

    def test_multi_record_evaluation_reports_zero_mismatches(self) -> None:
        records = self.completed_contexts[:8]
        report = evaluate_agent_orchestration(
            transactions=records,
            base_model=self.base_artifact.model,
            personalized_model=self.personalized_artifact.model,
            history_provider=self.history_provider,
            risk_profile=RiskProfile.BALANCED,
        )
        self.assertEqual(report.total_records, 8)
        self.assertEqual(report.successful_runs, 8)
        self.assertEqual(report.decision_mismatches, 0)
        self.assertEqual(report.average_tool_calls, 4.0)
        self.assertGreater(report.average_duration_ms, 0.0)


class AgentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        evidence_path = Path(cls._temporary.name) / "evidence.json"
        prepare_dashboard_evidence(count=30, seed=911, output=evidence_path)
        app = create_app(
            DashboardSettings(repository_root=ROOT, evidence_path=evidence_path)
        )
        cls._client_context = TestClient(app)
        cls.client = cls._client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_context.__exit__(None, None, None)
        cls._temporary.cleanup()

    def test_agent_capabilities_endpoint(self) -> None:
        response = self.client.get("/api/agent/capabilities")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["agent_model_mode"], "deterministic_offline")
        self.assertFalse(body["merchant_history_available"])
        self.assertFalse(body["mutating_payment_tools_enabled"])
        self.assertIn("get_customer_history", body["available_tools"])
        self.assertIn("optimize_block", body["available_tools"])

    def test_agent_decide_endpoint_returns_structured_trace_and_decision(self) -> None:
        payload = {
            "transaction": {
                "transaction_id": "API-AGENT-001",
                "estimated_amount_paise": 65000,
                "city": "hyderabad",
                "distance_km": "18.4",
                "estimated_duration_minutes": 42,
                "surge_multiplier": "1.18",
                "timestamp": "2027-01-15T18:30:00+05:30",
                "risk_profile": "balanced",
                "customer_profile": "stable_history",
            }
        }
        response = self.client.post("/api/agent/decide", json=payload)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["run_id"])
        self.assertGreater(body["decision"]["recommended_block_paise"], 0)
        self.assertEqual(body["decision"]["risk_profile"], "balanced")
        self.assertEqual(body["explanation"]["renderer"], "deterministic_phase_9")
        self.assertEqual(len(body["tool_trace"]), 4)

        # Test trace lookup by run_id
        run_id = body["run_id"]
        trace_res = self.client.get(f"/api/agent/runs/{run_id}")
        self.assertEqual(trace_res.status_code, 200)
        self.assertEqual(trace_res.json()["run_id"], run_id)

    def test_agent_run_not_found_returns_404(self) -> None:
        response = self.client.get("/api/agent/runs/RUN-NONEXISTENT")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "agent_run_not_found")


if __name__ == "__main__":
    unittest.main()
