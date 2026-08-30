import unittest

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.reserve_pay.errors import (
    IdempotencyConflictError,
    InsufficientReservedFundsError,
    InvalidReserveStateError,
)
from reserve_pay_optimizer.reserve_pay.mock_provider import MockReserveProvider
from reserve_pay_optimizer.reserve_pay.models import (
    CreateBlockRequest,
    DebitBlockRequest,
    GetBlockStatusRequest,
    IncreaseBlockRequest,
    ReleaseBlockRequest,
)
from reserve_pay_optimizer.reserve_pay.state import ReserveBlockStatus


class MockReserveProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockReserveProvider()
        self.create_request = CreateBlockRequest(
            "TXN-1", "C-1", Money(100_000), "create-1"
        )

    def create(self):
        return self.provider.create_block(self.create_request)

    def assert_accounting(self, block):
        self.assertEqual(
            block.debited_amount.amount_paise
            + block.released_amount.amount_paise
            + block.remaining_amount.amount_paise,
            block.authorized_amount.amount_paise,
        )

    def test_create_is_exact_normalized_and_deterministic(self):
        result = self.create()
        block = result.block
        self.assertEqual(block.block_id, "mock_blk_000001")
        self.assertEqual(block.authorized_amount, Money(100_000))
        self.assertEqual(block.remaining_amount, Money(100_000))
        self.assertEqual(block.status, ReserveBlockStatus.AUTHORIZED)
        self.assertEqual(block.provider_reference, block.block_id)
        self.assert_accounting(block)

    def test_create_idempotency_replays_and_conflicts(self):
        first = self.create()
        replay = self.provider.create_block(self.create_request)
        self.assertIs(first, replay)
        self.assertEqual(len(self.provider.operation_attempts), 1)
        with self.assertRaises(IdempotencyConflictError):
            self.provider.create_block(
                CreateBlockRequest("TXN-1", "C-1", Money(120_000), "create-1")
            )
        self.assertEqual(len(self.provider.operation_attempts), 1)

    def test_increase_is_idempotent_and_updates_only_authorized_and_remaining(self):
        block = self.create().block
        request = IncreaseBlockRequest(block.block_id, "TXN-1", Money(20_000), "inc-1")
        first = self.provider.increase_block(request)
        replay = self.provider.increase_block(request)
        self.assertIs(first, replay)
        self.assertEqual(first.block.authorized_amount.amount_paise, 120_000)
        self.assertEqual(first.block.remaining_amount.amount_paise, 120_000)
        self.assert_accounting(first.block)

    def test_partial_then_full_debit_and_duplicate_is_not_applied_twice(self):
        block = self.create().block
        first_request = DebitBlockRequest(block.block_id, "TXN-1", Money(70_000), "d-1")
        partial = self.provider.debit_block(first_request)
        replay = self.provider.debit_block(first_request)
        self.assertIs(partial, replay)
        self.assertEqual(partial.block.status, ReserveBlockStatus.PARTIALLY_DEBITED)
        self.assertEqual(partial.block.remaining_amount.amount_paise, 30_000)
        self.assert_accounting(partial.block)
        full = self.provider.debit_block(
            DebitBlockRequest(block.block_id, "TXN-1", Money(30_000), "d-2")
        )
        self.assertEqual(full.block.status, ReserveBlockStatus.DEBITED)
        self.assertEqual(full.block.remaining_amount.amount_paise, 0)
        self.assert_accounting(full.block)
        with self.assertRaises(InvalidReserveStateError):
            self.provider.debit_block(
                DebitBlockRequest(block.block_id, "TXN-1", Money(1), "d-3")
            )

    def test_over_debit_rejected_without_state_change(self):
        block = self.create().block
        with self.assertRaises(InsufficientReservedFundsError) as caught:
            self.provider.debit_block(
                DebitBlockRequest(block.block_id, "TXN-1", Money(100_001), "d-over")
            )
        self.assertEqual(caught.exception.safe_metadata["shortfall_paise"], 1)
        current = self.provider.get_block_status(GetBlockStatusRequest(block.block_id)).block
        self.assertEqual(current, block)

    def test_release_is_full_remaining_only_and_idempotent(self):
        block = self.create().block
        partial = self.provider.debit_block(
            DebitBlockRequest(block.block_id, "TXN-1", Money(72_000), "d-1")
        ).block
        with self.assertRaises(InvalidReserveStateError):
            self.provider.release_block(
                ReleaseBlockRequest(block.block_id, "TXN-1", Money(10_000), "r-part")
            )
        request = ReleaseBlockRequest(
            block.block_id, "TXN-1", partial.remaining_amount, "r-full"
        )
        released = self.provider.release_block(request)
        replay = self.provider.release_block(request)
        self.assertIs(released, replay)
        self.assertEqual(released.block.status, ReserveBlockStatus.RELEASED)
        self.assertEqual(released.block.debited_amount.amount_paise, 72_000)
        self.assertEqual(released.block.released_amount.amount_paise, 28_000)
        self.assert_accounting(released.block)
        with self.assertRaises(InvalidReserveStateError):
            self.provider.release_block(
                ReleaseBlockRequest(block.block_id, "TXN-1", Money(1), "r-after")
            )

    def test_transaction_identity_and_positive_operations_are_enforced(self):
        block = self.create().block
        with self.assertRaises(InvalidReserveStateError):
            self.provider.get_block_status(
                GetBlockStatusRequest(block.block_id, "OTHER-TXN")
            )
        with self.assertRaises(ValueError):
            DebitBlockRequest(
                block.block_id,
                "TXN-1",
                Money.from_non_negative_paise(0),
                "zero",
            )
