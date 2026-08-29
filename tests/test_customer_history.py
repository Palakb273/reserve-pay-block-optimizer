from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.personalization.history import (
    InMemoryCustomerHistoryProvider,
    calculate_customer_history_features,
)
from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.prediction.dataset import PredictionRecord
from tests.personalization_fixtures import BASE_TIME, context_at, outcome_at


class CustomerHistoryTests(unittest.TestCase):
    def test_hand_computable_history_formulas(self) -> None:
        records = tuple(
            PredictionRecord(
                context_at(f"H-{index}", "C-A", BASE_TIME, 10000),
                outcome_at(
                    f"H-{index}", BASE_TIME, actual
                ),
            )
            for index, actual in enumerate((10000, 11000, 9000), start=1)
        )
        features = calculate_customer_history_features("C-A", records)
        self.assertEqual(features.completed_ride_count, 3)
        self.assertEqual(features.mean_fare_ratio, Decimal(1))
        self.assertEqual(features.overrun_rate, Decimal(1) / Decimal(3))
        self.assertEqual(features.mean_positive_overrun_ratio, Decimal("0.1"))
        expected_stddev = (Decimal("0.02") / Decimal(3)).sqrt()
        self.assertEqual(features.fare_ratio_stddev, expected_stddev)

    def test_zero_and_one_record_stddev_definitions(self) -> None:
        zero = calculate_customer_history_features("C-A", ())
        self.assertEqual(zero.completed_ride_count, 0)
        self.assertEqual(zero.mean_fare_ratio, Decimal(1))
        self.assertEqual(zero.fare_ratio_stddev, Decimal(0))
        one_record = PredictionRecord(
            context_at("H-1", "C-A", BASE_TIME, 10000),
            outcome_at("H-1", BASE_TIME, 10500),
        )
        one = calculate_customer_history_features("C-A", (one_record,))
        self.assertEqual(one.fare_ratio_stddev, Decimal(0))
        self.assertEqual(one.overrun_rate, Decimal(1))

    def test_provider_excludes_current_equal_time_future_and_other_customer(self) -> None:
        current = context_at("CURRENT", "C-A", BASE_TIME, 10000)
        contexts = (
            context_at("PAST", "C-A", BASE_TIME.replace(hour=8), 10000),
            context_at("EQUAL", "C-A", BASE_TIME, 10000),
            context_at("FUTURE", "C-A", BASE_TIME, 10000),
            context_at("CURRENT", "C-A", BASE_TIME, 10000),
            context_at("OTHER", "C-B", BASE_TIME.replace(hour=8), 10000),
        )
        outcomes = (
            outcome_at("PAST", BASE_TIME.replace(hour=9), 10100),
            outcome_at("EQUAL", BASE_TIME, 10200),
            outcome_at("FUTURE", BASE_TIME.replace(hour=11), 10300),
            outcome_at("CURRENT", BASE_TIME.replace(hour=12), 10400),
            outcome_at("OTHER", BASE_TIME.replace(hour=9), 15000),
        )
        provider = InMemoryCustomerHistoryProvider(contexts, outcomes)
        eligible = provider.get_completed_history(
            "C-A", BASE_TIME, current_transaction_id="CURRENT"
        )
        self.assertEqual([record.context.transaction_id for record in eligible], ["PAST"])
        self.assertEqual(provider.features_for(current).completed_ride_count, 1)

    def test_provider_rejects_completion_before_its_own_start(self) -> None:
        with self.assertRaises(DomainValidationError):
            InMemoryCustomerHistoryProvider(
                (context_at("BAD", "C-A", BASE_TIME, 10000),),
                (outcome_at("BAD", BASE_TIME.replace(hour=9), 10000),),
            )

    def test_typed_history_rejects_invalid_counts_and_rates(self) -> None:
        with self.assertRaises(ValueError):
            CustomerHistoryFeatures(
                "C-A", -1, Decimal(1), Decimal(0), Decimal(0), Decimal(0)
            )
        with self.assertRaises(ValueError):
            CustomerHistoryFeatures(
                "C-A", 3, Decimal(1), Decimal(0), Decimal("1.1"), Decimal(0)
            )


if __name__ == "__main__":
    unittest.main()
