from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.services.evaluation import (
    aggregate_evaluations,
    evaluate_transaction,
)
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from tests.fixtures import baseline_fixture, make_context, make_outcome


def evaluation(block_paise: int, actual_paise: int):
    transaction = make_context(amount_paise=65000)
    decision = ReserveDecision(
        transaction_id=transaction.transaction_id,
        strategy="test_strategy",
        strategy_version="1",
        block_amount=type(transaction.estimated_amount)(amount_paise=block_paise),
    )
    return evaluate_transaction(
        transaction,
        decision,
        make_outcome(amount_paise=actual_paise),
    )


class TransactionEvaluationTests(unittest.TestCase):
    def test_success_and_excess_block(self) -> None:
        result = evaluation(block_paise=78000, actual_paise=72000)

        self.assertTrue(result.collection_success)
        self.assertFalse(result.is_under_blocked)
        self.assertEqual(result.excess_block.amount_paise, 6000)
        self.assertEqual(result.under_block.amount_paise, 0)

    def test_failure_and_under_block(self) -> None:
        result = evaluation(block_paise=65000, actual_paise=72000)

        self.assertFalse(result.collection_success)
        self.assertTrue(result.is_under_blocked)
        self.assertEqual(result.excess_block.amount_paise, 0)
        self.assertEqual(result.under_block.amount_paise, 7000)

    def test_equal_block_and_actual_is_success_with_zero_deltas(self) -> None:
        result = evaluation(block_paise=65000, actual_paise=65000)

        self.assertTrue(result.collection_success)
        self.assertFalse(result.is_under_blocked)
        self.assertEqual(result.excess_block.amount_paise, 0)
        self.assertEqual(result.under_block.amount_paise, 0)

    def test_mismatched_transaction_ids_are_rejected(self) -> None:
        transaction = make_context("TXN-001")
        decision = ExactEstimateStrategy().calculate_block(transaction)

        with self.assertRaises(DomainValidationError) as caught:
            evaluate_transaction(transaction, decision, make_outcome("TXN-OTHER"))

        self.assertEqual(caught.exception.issues[0].code, "transaction_id_mismatch")


class AggregationTests(unittest.TestCase):
    def test_exact_estimate_metrics_match_fixture(self) -> None:
        transactions, outcomes = baseline_fixture()
        outcome_by_id = {outcome.transaction_id: outcome for outcome in outcomes}
        strategy = ExactEstimateStrategy()
        evaluations = tuple(
            evaluate_transaction(
                transaction,
                strategy.calculate_block(transaction),
                outcome_by_id[transaction.transaction_id],
            )
            for transaction in transactions
        )

        metrics = aggregate_evaluations(evaluations)

        self.assertEqual(metrics.transaction_count, 3)
        self.assertEqual(metrics.collection_success_count, 1)
        self.assertEqual(metrics.collection_success_rate, Decimal("0.333333"))
        self.assertEqual(metrics.under_block_count, 2)
        self.assertEqual(metrics.under_block_rate, Decimal("0.666667"))
        self.assertEqual(metrics.average_excess_block.amount_paise, 1000)
        self.assertEqual(metrics.average_under_block.amount_paise, 6667)
        self.assertEqual(metrics.total_blocked_amount.amount_paise, 180000)
        self.assertEqual(metrics.total_actual_amount.amount_paise, 197000)
        self.assertEqual(metrics.capital_efficiency, Decimal("0.983333"))
        self.assertEqual(
            metrics.average_excess_block_ratio, Decimal("0.015385")
        )

    def test_empty_dataset_is_rejected(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            aggregate_evaluations(())

        self.assertEqual(caught.exception.issues[0].code, "empty_dataset")


if __name__ == "__main__":
    unittest.main()

