import json
import unittest
from datetime import timedelta

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.dynamic.models import RideContextUpdate, RideUpdateReason
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.explainability.evidence import (
    build_dynamic_decision_evidence,
    build_reserve_decision_evidence,
)
from reserve_pay_optimizer.explainability.models import (
    AuthorizationStatus,
    DecisionType,
    ExplanationLevel,
)
from reserve_pay_optimizer.explainability.renderer import TemplateExplanationRenderer
from reserve_pay_optimizer.explainability.service import ExplanationService
from reserve_pay_optimizer.policy.risk import RiskProfile
from tests.dynamic_fixtures import DeterministicPersonalizedPredictor, context


class ExplainabilityTests(unittest.TestCase):
    def sources(self, *, history_count=5, estimate=70000):
        predictor = DeterministicPersonalizedPredictor(history_count)
        service = DynamicRideService(predictor)
        ride = context(estimate=estimate)
        session = service.start_dynamic_session(ride, RiskProfile.BALANCED)
        return service, session

    def test_static_evidence_reuses_every_authoritative_financial_fact(self):
        _, session = self.sources()
        facts = build_reserve_decision_evidence(
            session.initial_context,
            session.initial_prediction,
            session.initial_optimization,
        )
        optimization = session.initial_optimization
        self.assertEqual(facts.recommended_block, optimization.recommended_block)
        self.assertEqual(
            facts.estimated_collection_probability,
            optimization.estimated_collection_probability,
        )
        self.assertEqual(facts.expected_excess_block, optimization.expected_excess_block)
        self.assertEqual(facts.objective_components, optimization.score_components)
        self.assertEqual(facts.risk_policy, optimization.risk_policy)
        self.assertEqual(
            set(facts.prediction_summary.to_dict()),
            {"0.50", "0.90", "0.95", "0.97", "0.99"},
        )
        self.assertGreaterEqual(len(facts.candidate_comparison), 1)
        self.assertTrue(any(item.selected for item in facts.candidate_comparison))

    def test_personalized_history_is_aggregated_private_and_nonjudgmental(self):
        _, session = self.sources(history_count=8)
        facts = build_reserve_decision_evidence(
            session.initial_context,
            session.initial_prediction,
            session.initial_optimization,
        )
        self.assertEqual(facts.prediction_mode, "personalized")
        self.assertEqual(facts.history_summary.completed_ride_count, 8)
        serialized = json.dumps(facts.to_dict()).casefold()
        for forbidden in (
            "customer_overrun_bias",
            "customer_variance_multiplier",
            "pricing_noise",
            "actual_amount",
            "risky customer",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_cold_start_uses_base_model_language_without_fabricated_history(self):
        _, session = self.sources(history_count=1)
        rendered = ExplanationService().explain_reserve_decision(
            session.initial_context,
            session.initial_prediction,
            session.initial_optimization,
            ExplanationLevel.DETAILED,
        )
        self.assertEqual(rendered.facts.prediction_mode, "base")
        self.assertIn("below the personalization threshold", rendered.text)
        self.assertIn("base transaction-level prediction model", rendered.text)

    def test_template_renderer_is_offline_deterministic_and_cannot_modify_decision(self):
        _, session = self.sources()
        facts = build_reserve_decision_evidence(
            session.initial_context,
            session.initial_prediction,
            session.initial_optimization,
        )
        renderer = TemplateExplanationRenderer()
        before = session.initial_optimization.recommended_block
        first = renderer.render(facts, ExplanationLevel.DETAILED)
        second = renderer.render(facts, ExplanationLevel.DETAILED)
        self.assertEqual(first, second)
        self.assertEqual(session.initial_optimization.recommended_block, before)
        self.assertIn("not guarantees", first)
        self.assertNotIn("caused exactly", first.casefold())

    def test_fingerprint_is_stable_and_decision_sensitive(self):
        _, first_session = self.sources(estimate=70000)
        _, second_session = self.sources(estimate=71000)
        first = build_reserve_decision_evidence(
            first_session.initial_context,
            first_session.initial_prediction,
            first_session.initial_optimization,
        )
        same = build_reserve_decision_evidence(
            first_session.initial_context,
            first_session.initial_prediction,
            first_session.initial_optimization,
        )
        changed = build_reserve_decision_evidence(
            second_session.initial_context,
            second_session.initial_prediction,
            second_session.initial_optimization,
        )
        self.assertEqual(first.explanation_id, same.explanation_id)
        self.assertNotEqual(first.explanation_id, changed.explanation_id)
        self.assertEqual(len(first.explanation_id), 64)

    def test_dynamic_evidence_contains_only_changed_fields_and_exact_old_new_facts(self):
        service, session = self.sources()
        update = RideContextUpdate(
            event_id="DYN-EXPLAIN-1",
            transaction_id=session.transaction_id,
            sequence_number=1,
            observed_at=session.started_at + timedelta(minutes=10),
            reason=RideUpdateReason.FARE_ESTIMATE_CHANGE,
            revised_estimated_amount=Money(76000),
        )
        application = service.apply_context_update(session, update)
        facts = build_dynamic_decision_evidence(
            application.session, application.decision
        )
        dynamic = facts.dynamic_context
        self.assertEqual(facts.decision_type, DecisionType.DYNAMIC_REOPTIMIZATION)
        self.assertEqual([item.field for item in dynamic.changed_fields], ["estimated_amount_paise"])
        self.assertEqual(
            dynamic.previous_quantiles.to_dict()["0.97"],
            application.decision.previous_q97.amount_paise,
        )
        self.assertEqual(
            dynamic.revised_quantiles.to_dict()["0.99"],
            application.decision.revised_q99.amount_paise,
        )
        self.assertEqual(
            dynamic.additional_block_required,
            application.decision.additional_block_required,
        )
        self.assertEqual(dynamic.authorization_status, AuthorizationStatus.RECOMMENDATION_ONLY)

    def test_dynamic_confirmation_language_changes_without_financial_recalculation(self):
        service, session = self.sources()
        application = service.apply_context_update(
            session,
            RideContextUpdate(
                event_id="DYN-EXPLAIN-2",
                transaction_id=session.transaction_id,
                sequence_number=1,
                observed_at=session.started_at + timedelta(minutes=10),
                reason=RideUpdateReason.TRAFFIC_CHANGE,
                revised_estimated_amount=Money(76000),
                revised_estimated_duration_minutes=55,
            ),
        )
        unconfirmed = ExplanationService().explain_dynamic_decision(
            application.session, application.decision, ExplanationLevel.DETAILED
        )
        self.assertIn("recommendation only", unconfirmed.text.casefold())
        confirmed_session = service.confirm_block_authorized(
            application.session,
            application.decision,
            application.decision.recommended_target_block,
        )
        confirmed = ExplanationService().explain_dynamic_decision(
            confirmed_session, application.decision, ExplanationLevel.DETAILED
        )
        self.assertEqual(
            confirmed.facts.dynamic_context.authorization_status,
            AuthorizationStatus.SIMULATED_CONFIRMED,
        )
        self.assertIn("simulated/application session state", confirmed.text)
        self.assertIn("max(recommended target block", confirmed.text)

        mock_confirmed = ExplanationService().explain_dynamic_decision(
            confirmed_session,
            application.decision,
            ExplanationLevel.DETAILED,
            authorization_status=AuthorizationStatus.MOCK_PROVIDER_CONFIRMED,
        )
        self.assertEqual(
            mock_confirmed.facts.dynamic_context.authorization_status,
            AuthorizationStatus.MOCK_PROVIDER_CONFIRMED,
        )
        self.assertIn("configured mock reserve provider", mock_confirmed.text)
        self.assertIn("No external or real payment network was called", mock_confirmed.text)

    def test_validation_metrics_are_factual_counts_not_composite_scores(self):
        _, session = self.sources()
        service = ExplanationService()
        service.explain_reserve_decision(
            session.initial_context,
            session.initial_prediction,
            session.initial_optimization,
        )
        self.assertEqual(
            service.metrics.to_dict(),
            {
                "explanations_generated": 1,
                "structured_explanations_valid": 1,
                "numeric_decision_consistency": 1,
                "fallback_count": 1,
                "llm_renderer_failures": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
