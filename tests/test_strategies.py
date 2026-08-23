from decimal import Decimal
import inspect
import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from tests.fixtures import make_context, make_outcome


class ExactEstimateStrategyTests(unittest.TestCase):
    def test_returns_exact_estimated_amount_and_transaction_id(self) -> None:
        transaction = make_context(amount_paise=65000)

        decision = ExactEstimateStrategy().calculate_block(transaction)

        self.assertEqual(decision.transaction_id, transaction.transaction_id)
        self.assertEqual(decision.block_amount, transaction.estimated_amount)
        self.assertEqual(decision.strategy, "exact_estimate")

    def test_strategy_interface_cannot_receive_an_outcome(self) -> None:
        parameters = tuple(
            inspect.signature(ExactEstimateStrategy.calculate_block).parameters
        )
        self.assertEqual(parameters, ("self", "transaction"))
        self.assertNotIn("actual_amount", set(inspect.get_annotations(RideTransactionContext)))

    def test_decision_does_not_change_with_post_ride_outcome(self) -> None:
        transaction = make_context()
        strategy = ExactEstimateStrategy()

        decision_before_outcome = strategy.calculate_block(transaction)
        _ = make_outcome(amount_paise=62000)
        _ = make_outcome(amount_paise=90000)
        decision_after_outcomes = strategy.calculate_block(transaction)

        self.assertEqual(decision_before_outcome, decision_after_outcomes)


class FixedBufferStrategyTests(unittest.TestCase):
    def test_default_twenty_percent_buffer(self) -> None:
        decision = FixedBufferStrategy().calculate_block(make_context(amount_paise=65000))

        self.assertEqual(decision.block_amount.amount_paise, 78000)
        self.assertEqual(decision.strategy, "fixed_buffer_20")
        self.assertEqual(dict(decision.parameters), {"buffer_percentage": "20"})

    def test_configurable_buffer(self) -> None:
        decision = FixedBufferStrategy(Decimal("10")).calculate_block(
            make_context(amount_paise=65000)
        )

        self.assertEqual(decision.block_amount.amount_paise, 71500)
        self.assertEqual(decision.strategy, "fixed_buffer_10")

    def test_exact_paise_result_needs_no_extra_rounding(self) -> None:
        decision = FixedBufferStrategy().calculate_block(make_context(amount_paise=5))

        self.assertEqual(decision.block_amount.amount_paise, 6)

    def test_fractional_paise_is_rounded_up(self) -> None:
        decision = FixedBufferStrategy().calculate_block(make_context(amount_paise=1))

        self.assertEqual(decision.block_amount.amount_paise, 2)

    def test_fractional_configurable_buffer_is_rounded_up(self) -> None:
        decision = FixedBufferStrategy(Decimal("12.5")).calculate_block(
            make_context(amount_paise=100)
        )

        self.assertEqual(decision.block_amount.amount_paise, 113)

    def test_large_valid_amount_uses_exact_arithmetic(self) -> None:
        transaction = make_context(amount_paise=7_000_000_000_000_000_000)

        decision = FixedBufferStrategy().calculate_block(transaction)

        self.assertEqual(decision.block_amount.amount_paise, 8_400_000_000_000_000_000)

    def test_overflow_is_rejected(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            FixedBufferStrategy().calculate_block(
                make_context(amount_paise=9_000_000_000_000_000_000)
            )

        self.assertEqual(caught.exception.issues[0].field, "block_amount_paise")
        self.assertEqual(caught.exception.issues[0].code, "out_of_range")

    def test_invalid_buffer_configuration_is_rejected(self) -> None:
        invalid_values = (
            Decimal("-0.01"),
            Decimal("NaN"),
            Decimal("Infinity"),
            20.0,
            True,
            "20",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(DomainValidationError):
                FixedBufferStrategy(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
