import inspect
import os
import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from reserve_pay_optimizer.domain.mobility import RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.dynamic.models import RideContextUpdate, RideUpdateReason
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.policy.risk import RiskProfile
from reserve_pay_optimizer.reserve_pay.errors import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderRejectedError,
    UnsupportedProviderOperation,
)
from reserve_pay_optimizer.reserve_pay.mock_provider import (
    MockFailureConfig,
    MockReserveProvider,
)
from reserve_pay_optimizer.reserve_pay.models import (
    CreateBlockRequest,
    DebitBlockRequest,
    DynamicExecutionStatus,
    GetBlockStatusRequest,
    IncreaseBlockRequest,
    SettlementStatus,
)
from reserve_pay_optimizer.reserve_pay.provider import ReservePayProvider
from reserve_pay_optimizer.reserve_pay.razorpay_provider import (
    RazorpayProvider,
    RazorpayProviderConfig,
)
from reserve_pay_optimizer.reserve_pay.service import ReservePayService, RetryConfig
from reserve_pay_optimizer.reserve_pay.state import ReserveBlockStatus
from tests.dynamic_fixtures import DeterministicPersonalizedPredictor, context, outcome


class ReservePayServiceTests(unittest.TestCase):
    def decision(self, amount=100_000):
        return ReserveDecision("TXN-S", "test", "1", Money(amount))

    def authorize(self, service, amount=100_000):
        return service.authorize_initial_block(
            self.decision(amount), customer_reference="C-S", idempotency_key="initial"
        )

    def test_provider_contract_and_razorpay_boundary(self):
        mock = MockReserveProvider()
        razorpay = RazorpayProvider(RazorpayProviderConfig("key", "secret"))
        self.assertIsInstance(mock, ReservePayProvider)
        self.assertIsInstance(razorpay, ReservePayProvider)
        self.assertFalse(razorpay.capabilities.supports_create)
        with self.assertRaises(UnsupportedProviderOperation) as caught:
            razorpay.create_block(CreateBlockRequest("T", "C", Money(100), "k"))
        serialized = str(caught.exception.to_dict()) + repr(razorpay.config)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("key'", serialized)

    def test_missing_credentials_fail_without_leaking_environment_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderConfigurationError) as caught:
                RazorpayProviderConfig.from_environment()
        self.assertNotIn("secret=", str(caught.exception).casefold())

    def test_transient_failure_retries_with_the_same_idempotency_key(self):
        provider = MockReserveProvider(
            MockFailureConfig(transient_failures={"create": 1})
        )
        sleeps = []
        service = ReservePayService(
            provider,
            retry_config=RetryConfig(max_attempts=3, delay_seconds=0),
            sleeper=sleeps.append,
        )
        result = self.authorize(service)
        self.assertEqual(result.block.status, ReserveBlockStatus.AUTHORIZED)
        self.assertEqual(provider.operation_attempts, [("create", "initial")] * 2)
        self.assertEqual(sleeps, [0])

    def test_permanent_failure_is_not_retried(self):
        provider = MockReserveProvider(MockFailureConfig(fail_next_create=True))
        service = ReservePayService(provider, sleeper=lambda _: None)
        with self.assertRaises(ProviderRejectedError):
            self.authorize(service)
        self.assertEqual(provider.operation_attempts, [("create", "initial")])

    def test_provider_result_cannot_change_transaction_identity(self):
        class CorruptingProvider(MockReserveProvider):
            def create_block(self, request):
                result = super().create_block(request)
                return replace(
                    result,
                    block=replace(result.block, transaction_id="CHANGED-BY-PROVIDER"),
                )

        service = ReservePayService(CorruptingProvider())
        with self.assertRaises(ProviderResponseError):
            self.authorize(service)

    def test_settlement_debits_actual_then_releases_remainder_idempotently(self):
        provider = MockReserveProvider()
        service = ReservePayService(provider)
        block = self.authorize(service).block
        ride_outcome = RideTransactionOutcome(
            "TXN-S", Money(79_500), context().timestamp + timedelta(minutes=80)
        )
        result = service.settle_completed_transaction(
            ride_outcome, block_id=block.block_id, idempotency_key="settle-1"
        )
        replay = service.settle_completed_transaction(
            ride_outcome, block_id=block.block_id, idempotency_key="settle-1"
        )
        self.assertIs(result, replay)
        self.assertEqual(result.status, SettlementStatus.SETTLED)
        self.assertEqual(result.already_debited_before_settlement.amount_paise, 0)
        self.assertEqual(result.outstanding_due.amount_paise, 79_500)
        self.assertEqual(result.newly_debited.amount_paise, 79_500)
        self.assertEqual(result.debited_amount.amount_paise, 79_500)
        self.assertEqual(result.released_amount.amount_paise, 20_500)
        self.assertEqual(result.overpaid_amount.amount_paise, 0)
        self.assertEqual(result.final_block.status, ReserveBlockStatus.RELEASED)

    def test_settlement_after_partial_debit_collects_only_outstanding_due(self):
        provider = MockReserveProvider()
        service = ReservePayService(provider)
        block = self.authorize(service).block
        service.debit_block(
            DebitBlockRequest(
                block.block_id, "TXN-S", Money(20_000), "partial-before-settlement"
            )
        )
        ride_outcome = RideTransactionOutcome(
            "TXN-S", Money(70_000), context().timestamp + timedelta(minutes=80)
        )

        result = service.settle_completed_transaction(
            ride_outcome, block_id=block.block_id, idempotency_key="settle-partial"
        )
        replay = service.settle_completed_transaction(
            ride_outcome, block_id=block.block_id, idempotency_key="settle-partial"
        )

        self.assertIs(result, replay)
        self.assertEqual(result.already_debited_before_settlement.amount_paise, 20_000)
        self.assertEqual(result.outstanding_due.amount_paise, 50_000)
        self.assertEqual(result.newly_debited.amount_paise, 50_000)
        self.assertEqual(result.debited_amount.amount_paise, 70_000)
        self.assertEqual(result.released_amount.amount_paise, 30_000)
        self.assertEqual(result.shortfall.amount_paise, 0)
        self.assertEqual(result.status, SettlementStatus.SETTLED)
        self.assertEqual(result.final_block.status, ReserveBlockStatus.RELEASED)
        self.assertEqual(
            result.debited_amount.amount_paise
            + result.released_amount.amount_paise
            + result.final_block.remaining_amount.amount_paise,
            result.authorized_amount.amount_paise,
        )
        self.assertLessEqual(
            result.debited_amount.amount_paise, result.final_amount.amount_paise
        )

    def test_settlement_when_already_fully_paid_skips_debit_and_releases(self):
        provider = MockReserveProvider()
        service = ReservePayService(provider)
        block = self.authorize(service).block
        service.debit_block(
            DebitBlockRequest(block.block_id, "TXN-S", Money(70_000), "paid-before")
        )
        result = service.settle_completed_transaction(
            RideTransactionOutcome(
                "TXN-S", Money(70_000), context().timestamp + timedelta(minutes=80)
            ),
            block_id=block.block_id,
            idempotency_key="settle-paid",
        )
        self.assertEqual(result.outstanding_due.amount_paise, 0)
        self.assertEqual(result.newly_debited.amount_paise, 0)
        self.assertEqual(result.debited_amount.amount_paise, 70_000)
        self.assertEqual(result.released_amount.amount_paise, 30_000)
        self.assertEqual(result.status, SettlementStatus.SETTLED)

    def test_historical_overpayment_is_visible_and_not_debited_or_refunded(self):
        provider = MockReserveProvider()
        service = ReservePayService(provider)
        block = self.authorize(service).block
        service.debit_block(
            DebitBlockRequest(block.block_id, "TXN-S", Money(75_000), "overpaid-before")
        )
        result = service.settle_completed_transaction(
            RideTransactionOutcome(
                "TXN-S", Money(70_000), context().timestamp + timedelta(minutes=80)
            ),
            block_id=block.block_id,
            idempotency_key="settle-overpaid",
        )
        self.assertEqual(result.outstanding_due.amount_paise, 0)
        self.assertEqual(result.newly_debited.amount_paise, 0)
        self.assertEqual(result.debited_amount.amount_paise, 75_000)
        self.assertEqual(result.released_amount.amount_paise, 25_000)
        self.assertEqual(result.overpaid_amount.amount_paise, 5_000)
        self.assertEqual(
            result.status, SettlementStatus.OVERPAID_RECONCILIATION_REQUIRED
        )

    def test_under_block_settlement_reports_shortfall_and_does_not_debit(self):
        provider = MockReserveProvider()
        service = ReservePayService(provider)
        block = self.authorize(service, 70_000).block
        ride_outcome = RideTransactionOutcome(
            "TXN-S", Money(79_500), context().timestamp + timedelta(minutes=80)
        )
        result = service.settle_completed_transaction(
            ride_outcome, block_id=block.block_id, idempotency_key="settle-short"
        )
        self.assertEqual(result.status, SettlementStatus.INSUFFICIENT_RESERVED_FUNDS)
        self.assertEqual(result.shortfall.amount_paise, 9_500)
        self.assertEqual(result.debited_amount.amount_paise, 0)
        current = service.get_block_status(
            GetBlockStatusRequest(block.block_id, "TXN-S")
        ).block
        self.assertEqual(current.status, ReserveBlockStatus.AUTHORIZED)

    def test_shortfall_after_partial_debit_uses_only_outstanding_due(self):
        provider = MockReserveProvider()
        service = ReservePayService(provider)
        block = self.authorize(service, 70_000).block
        service.debit_block(
            DebitBlockRequest(block.block_id, "TXN-S", Money(20_000), "short-prior")
        )
        result = service.settle_completed_transaction(
            RideTransactionOutcome(
                "TXN-S", Money(79_500), context().timestamp + timedelta(minutes=80)
            ),
            block_id=block.block_id,
            idempotency_key="settle-short-partial",
        )
        self.assertEqual(result.outstanding_due.amount_paise, 59_500)
        self.assertEqual(result.newly_debited.amount_paise, 0)
        self.assertEqual(result.debited_amount.amount_paise, 20_000)
        self.assertEqual(result.shortfall.amount_paise, 9_500)
        self.assertEqual(
            result.status, SettlementStatus.INSUFFICIENT_RESERVED_FUNDS
        )
        self.assertEqual(result.final_block.remaining_amount.amount_paise, 50_000)

    def test_outcome_enters_only_the_settlement_method(self):
        forbidden = {
            "create_block",
            "authorize_initial_block",
            "increase_block",
            "debit_block",
            "release_block",
            "request_additional_block",
            "confirm_dynamic_increase",
        }
        for name in forbidden:
            signature = inspect.signature(getattr(ReservePayService, name))
            self.assertNotIn("outcome", signature.parameters)
            self.assertNotIn("actual_amount", signature.parameters)
        self.assertIn(
            "outcome",
            inspect.signature(ReservePayService.settle_completed_transaction).parameters,
        )


class DynamicReservePayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.ride = context()
        self.dynamic = DynamicRideService(DeterministicPersonalizedPredictor())
        self.initial_session = self.dynamic.start_dynamic_session(
            self.ride, RiskProfile.BALANCED
        )

    def update(self, sequence, estimate):
        return RideContextUpdate(
            event_id=f"U-{sequence}",
            transaction_id=self.ride.transaction_id,
            sequence_number=sequence,
            observed_at=self.ride.timestamp + timedelta(minutes=sequence * 10),
            reason=RideUpdateReason.TRAFFIC_CHANGE,
            revised_estimated_amount=Money(estimate),
        )

    def setup_execution(self, failure_config=None):
        provider = MockReserveProvider(failure_config)
        service = ReservePayService(
            provider, dynamic_service=self.dynamic, sleeper=lambda _: None
        )
        initial = service.authorize_initial_block(
            self.initial_session.initial_optimization.reserve_decision,
            customer_reference=self.ride.customer_id,
            idempotency_key="initial-dynamic",
        )
        return provider, service, initial

    def test_successful_provider_increase_then_confirms_phase8(self):
        provider, service, initial = self.setup_execution()
        application = self.dynamic.apply_context_update(
            self.initial_session, self.update(1, 75_000)
        )
        result = service.request_additional_block(
            application.session,
            application.decision,
            block_id=initial.block.block_id,
            idempotency_key="increase-1",
        )
        self.assertEqual(result.status, DynamicExecutionStatus.SUCCEEDED)
        self.assertEqual(
            result.session.current_authorized_block,
            application.decision.recommended_target_block,
        )
        self.assertEqual(
            provider.get_block_status(GetBlockStatusRequest(initial.block.block_id)).block.authorized_amount,
            result.session.current_authorized_block,
        )

    def test_failed_provider_increase_preserves_authorized_session_state(self):
        _, service, initial = self.setup_execution(
            MockFailureConfig(fail_next_increase=True)
        )
        application = self.dynamic.apply_context_update(
            self.initial_session, self.update(1, 75_000)
        )
        before = application.session.current_authorized_block
        result = service.request_additional_block(
            application.session,
            application.decision,
            block_id=initial.block.block_id,
            idempotency_key="increase-fail",
        )
        self.assertEqual(result.status, DynamicExecutionStatus.FAILED)
        self.assertEqual(result.session.current_authorized_block, before)
        self.assertNotEqual(
            application.decision.recommended_target_block,
            result.session.current_authorized_block,
        )

    def test_late_stale_success_requires_reconciliation_and_does_not_mutate_latest(self):
        _, service, initial = self.setup_execution()
        first = self.dynamic.apply_context_update(
            self.initial_session, self.update(1, 75_000)
        )
        provider_success = service.increase_block(
            IncreaseBlockRequest(
                initial.block.block_id,
                self.ride.transaction_id,
                first.decision.additional_block_required,
                "late-increase",
            )
        )
        latest = self.dynamic.apply_context_update(first.session, self.update(2, 81_000))
        result = service.confirm_dynamic_increase(
            latest.session, first.decision, provider_success
        )
        self.assertEqual(
            result.status, DynamicExecutionStatus.RECONCILIATION_REQUIRED
        )
        self.assertEqual(
            result.session.current_authorized_block,
            self.initial_session.current_authorized_block,
        )
        self.assertIsNotNone(result.provider_result)

    def test_end_to_end_mock_lifecycle(self):
        _, service, initial = self.setup_execution()
        session = self.initial_session
        for sequence, estimate in ((1, 75_000), (2, 81_000)):
            application = self.dynamic.apply_context_update(
                session, self.update(sequence, estimate)
            )
            execution = service.request_additional_block(
                application.session,
                application.decision,
                block_id=initial.block.block_id,
                idempotency_key=f"increase-{sequence}",
            )
            session = execution.session
        final_outcome = outcome(self.ride, actual=78_000)
        settlement = service.settle_completed_transaction(
            final_outcome,
            block_id=initial.block.block_id,
            idempotency_key="settle-dynamic",
        )
        self.assertEqual(settlement.status, SettlementStatus.SETTLED)
        self.assertEqual(settlement.debited_amount.amount_paise, 78_000)
        self.assertEqual(settlement.final_block.status, ReserveBlockStatus.RELEASED)
