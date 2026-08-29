import inspect
import unittest
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.dynamic.errors import DynamicSessionError
from reserve_pay_optimizer.dynamic.models import (
    DynamicReoptimizationDecision,
    DynamicRideSession,
    RideContextUpdate,
    RideUpdateReason,
)
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.policy.risk import RiskProfile
from tests.dynamic_fixtures import DeterministicPersonalizedPredictor, context


class DynamicSessionTests(unittest.TestCase):
    def setUp(self):
        self.predictor = DeterministicPersonalizedPredictor()
        self.service = DynamicRideService(self.predictor)
        self.context = context()
        self.session = self.service.start_dynamic_session(
            self.context, RiskProfile.BALANCED
        )

    def update(self, sequence=1, estimate=75000, *, event_id=None, minutes=None, **kwargs):
        return RideContextUpdate(
            event_id=event_id or f"EVENT-{sequence}",
            transaction_id=self.context.transaction_id,
            sequence_number=sequence,
            observed_at=self.context.timestamp + timedelta(minutes=minutes or sequence * 10),
            reason=RideUpdateReason.MULTIPLE_FACTORS,
            revised_estimated_amount=Money(estimate),
            **kwargs,
        )

    def test_start_runs_prediction_and_optimization_and_freezes_history(self):
        session = self.session
        self.assertEqual(session.session_version, 0)
        self.assertEqual(session.initial_authorized_block, session.current_authorized_block)
        self.assertEqual(session.risk_policy.profile, RiskProfile.BALANCED)
        self.assertEqual(session.history_snapshot.completed_ride_count, 5)
        self.assertEqual(session.latest_prediction.prediction_mode, "personalized")
        self.assertEqual(len(self.predictor.calls), 1)

    def test_update_changes_only_mutable_context_and_does_not_authorize(self):
        application = self.service.apply_context_update(
            self.session,
            self.update(
                revised_distance_km=Decimal("21.2"),
                revised_estimated_duration_minutes=55,
                revised_surge_multiplier=Decimal("1.20"),
            ),
        )
        updated = application.session
        self.assertEqual(updated.session_version, 1)
        self.assertEqual(updated.transaction_id, self.session.transaction_id)
        self.assertEqual(updated.current_context.customer_id, self.context.customer_id)
        self.assertEqual(updated.current_context.city, self.context.city)
        self.assertEqual(updated.current_context.timestamp, self.context.timestamp)
        self.assertEqual(updated.current_context.estimated_amount.amount_paise, 75000)
        self.assertEqual(updated.current_authorized_block, self.session.current_authorized_block)
        self.assertEqual(
            application.decision.additional_block_required.amount_paise,
            max(
                application.decision.recommended_target_block.amount_paise
                - self.session.current_authorized_block.amount_paise,
                0,
            ),
        )

    def test_confirmation_is_explicit_exact_and_non_decreasing(self):
        application = self.service.apply_context_update(self.session, self.update())
        decision = application.decision
        expected = Money(
            application.session.current_authorized_block.amount_paise
            + decision.additional_block_required.amount_paise
        )
        with self.assertRaises(DynamicSessionError) as caught:
            self.service.confirm_block_authorized(
                application.session, decision, Money(expected.amount_paise - 1)
            )
        self.assertEqual(caught.exception.code, "invalid_confirmation_amount")
        confirmed = self.service.confirm_block_authorized(
            application.session, decision, expected
        )
        self.assertEqual(confirmed.current_authorized_block, expected)
        self.assertGreaterEqual(
            confirmed.current_authorized_block.amount_paise,
            confirmed.initial_authorized_block.amount_paise,
        )

    def test_repeated_confirmed_updates_use_incremental_not_cumulative_delta(self):
        first = self.service.apply_context_update(self.session, self.update(1, 75000))
        first_total = Money(first.decision.recommended_target_block.amount_paise)
        confirmed = self.service.confirm_block_authorized(
            first.session, first.decision, first_total
        )
        second = self.service.apply_context_update(
            confirmed, self.update(2, 81000)
        )
        self.assertEqual(
            second.decision.additional_block_required.amount_paise,
            second.decision.recommended_target_block.amount_paise
            - first_total.amount_paise,
        )

    def test_equal_or_decreasing_target_requires_no_additional_and_no_release(self):
        equal_update = RideContextUpdate(
            event_id="EQUAL",
            transaction_id=self.context.transaction_id,
            sequence_number=1,
            observed_at=self.context.timestamp + timedelta(minutes=10),
            reason=RideUpdateReason.ROUTE_CHANGE,
            revised_distance_km=Decimal("18.1"),
        )
        equal = self.service.apply_context_update(self.session, equal_update)
        self.assertEqual(equal.decision.additional_block_required.amount_paise, 0)
        self.assertTrue(equal.decision.current_block_sufficient)
        lower = self.service.apply_context_update(
            self.session, self.update(1, 60000, event_id="LOWER")
        )
        self.assertLess(
            lower.decision.recommended_target_block.amount_paise,
            self.session.current_authorized_block.amount_paise,
        )
        self.assertEqual(lower.decision.additional_block_required.amount_paise, 0)
        self.assertEqual(lower.session.current_authorized_block, self.session.current_authorized_block)

    def test_unconfirmed_increase_is_not_assumed_by_next_update(self):
        first = self.service.apply_context_update(self.session, self.update(1, 75000))
        second = self.service.apply_context_update(first.session, self.update(2, 81000))
        self.assertEqual(
            second.decision.previous_authorized_block,
            self.session.current_authorized_block,
        )

    def test_stale_confirmation_is_rejected(self):
        first = self.service.apply_context_update(self.session, self.update(1, 75000))
        second = self.service.apply_context_update(first.session, self.update(2, 81000))
        with self.assertRaises(DynamicSessionError) as caught:
            self.service.confirm_block_authorized(
                second.session,
                first.decision,
                first.decision.recommended_target_block,
            )
        self.assertEqual(caught.exception.code, "stale_confirmation")

    def test_duplicate_event_replay_is_idempotent_and_conflict_is_rejected(self):
        update = self.update()
        first = self.service.apply_context_update(self.session, update)
        replay = self.service.apply_context_update(first.session, update)
        self.assertTrue(replay.replayed)
        self.assertIs(replay.session, first.session)
        conflicting = replace(update, revised_estimated_amount=Money(76000))
        with self.assertRaises(DynamicSessionError) as caught:
            self.service.apply_context_update(first.session, conflicting)
        self.assertEqual(caught.exception.code, "duplicate_event_conflict")

    def test_order_timestamp_and_transaction_identity_are_enforced(self):
        with self.assertRaises(DynamicSessionError) as order:
            self.service.apply_context_update(self.session, self.update(2, 75000))
        self.assertEqual(order.exception.code, "out_of_order_sequence")
        stale = replace(self.update(), observed_at=self.context.timestamp)
        with self.assertRaises(DynamicSessionError) as timestamp:
            self.service.apply_context_update(self.session, stale)
        self.assertEqual(timestamp.exception.code, "stale_timestamp")
        wrong = replace(self.update(), transaction_id="OTHER")
        with self.assertRaises(DynamicSessionError) as identity:
            self.service.apply_context_update(self.session, wrong)
        self.assertEqual(identity.exception.code, "transaction_id_mismatch")

    def test_history_snapshot_does_not_change_with_provider(self):
        self.predictor.history_provider.history_count = 99
        application = self.service.apply_context_update(self.session, self.update())
        self.assertEqual(application.session.history_snapshot.completed_ride_count, 5)
        self.assertEqual(application.decision.history_count, 5)
        self.assertEqual(self.predictor.calls[-1][2], self.context.timestamp)

    def test_cold_start_and_every_existing_risk_profile_work(self):
        cold_service = DynamicRideService(DeterministicPersonalizedPredictor(0))
        cold = cold_service.start_dynamic_session(self.context, RiskProfile.BALANCED)
        self.assertEqual(cold.latest_prediction.prediction_mode, "base")
        for profile in RiskProfile:
            session = self.service.start_dynamic_session(self.context, profile)
            self.assertEqual(session.risk_policy.profile, profile)

    def test_decision_and_service_accept_no_outcome_fields(self):
        forbidden = {"actual_amount", "outcome", "completed_at", "pricing_noise"}
        self.assertTrue(forbidden.isdisjoint({field.name for field in fields(DynamicRideSession)}))
        self.assertTrue(forbidden.isdisjoint({field.name for field in fields(DynamicReoptimizationDecision)}))
        signature = inspect.signature(self.service.apply_context_update)
        self.assertTrue(forbidden.isdisjoint(signature.parameters))

