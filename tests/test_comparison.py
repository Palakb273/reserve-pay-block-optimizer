import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from tests.fixtures import baseline_fixture, make_context, make_outcome


class RecordingStrategy:
    def __init__(self, strategy_id: str):
        self._strategy_id = strategy_id
        self.seen_transaction_ids: list[str] = []

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    def calculate_block(self, transaction):
        self.seen_transaction_ids.append(transaction.transaction_id)
        return ReserveDecision(
            transaction_id=transaction.transaction_id,
            strategy=self.strategy_id,
            strategy_version="test",
            block_amount=transaction.estimated_amount,
        )


class ComparisonTests(unittest.TestCase):
    def test_both_strategies_receive_the_same_transactions(self) -> None:
        transactions, outcomes = baseline_fixture()
        first = RecordingStrategy("first")
        second = RecordingStrategy("second")

        result = compare_strategies(transactions, outcomes, (first, second))

        expected_ids = [transaction.transaction_id for transaction in transactions]
        self.assertEqual(first.seen_transaction_ids, expected_ids)
        self.assertEqual(second.seen_transaction_ids, expected_ids)
        self.assertEqual(result.transaction_ids, tuple(expected_ids))

    def test_outcomes_are_matched_by_id_not_input_order(self) -> None:
        transactions, outcomes = baseline_fixture()

        result = compare_strategies(
            transactions,
            tuple(reversed(outcomes)),
            (ExactEstimateStrategy(), FixedBufferStrategy()),
        )

        metrics = {metric.strategy: metric for metric in result.metrics}
        self.assertEqual(metrics["exact_estimate"].collection_success_count, 1)
        self.assertEqual(metrics["fixed_buffer_20"].collection_success_count, 2)

    def test_duplicate_transaction_ids_are_rejected(self) -> None:
        transactions = (make_context("TXN-001"), make_context("TXN-001"))
        outcomes = (make_outcome("TXN-001"),)

        with self.assertRaises(DomainValidationError) as caught:
            compare_strategies(transactions, outcomes, (ExactEstimateStrategy(),))

        self.assertIn(
            "duplicate_transaction_id", {issue.code for issue in caught.exception.issues}
        )

    def test_duplicate_outcome_ids_are_rejected(self) -> None:
        transactions = (make_context("TXN-001"),)
        outcomes = (make_outcome("TXN-001"), make_outcome("TXN-001"))

        with self.assertRaises(DomainValidationError) as caught:
            compare_strategies(transactions, outcomes, (ExactEstimateStrategy(),))

        self.assertIn(
            "duplicate_outcome_id", {issue.code for issue in caught.exception.issues}
        )

    def test_missing_outcome_is_rejected(self) -> None:
        transactions = (make_context("TXN-001"), make_context("TXN-002"))

        with self.assertRaises(DomainValidationError) as caught:
            compare_strategies(
                transactions, (make_outcome("TXN-001"),), (ExactEstimateStrategy(),)
            )

        self.assertIn("missing_outcome", {i.code for i in caught.exception.issues})

    def test_unexpected_outcome_is_rejected(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            compare_strategies(
                (make_context("TXN-001"),),
                (make_outcome("TXN-001"), make_outcome("TXN-002")),
                (ExactEstimateStrategy(),),
            )

        self.assertIn("unexpected_outcome", {i.code for i in caught.exception.issues})


if __name__ == "__main__":
    unittest.main()
