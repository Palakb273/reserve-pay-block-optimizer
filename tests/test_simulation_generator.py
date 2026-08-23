from dataclasses import fields
from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.services.mobility_validation import parse_mobility_transaction
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class SimulationGeneratorTests(unittest.TestCase):
    def test_same_seed_and_config_produce_identical_records(self) -> None:
        config = SimulationConfig(transaction_count=50, seed=42)

        first = simulate_transactions(config)
        second = simulate_transactions(config)

        self.assertEqual(first, second)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_different_seeds_produce_different_records(self) -> None:
        first = simulate_transactions(SimulationConfig(transaction_count=20, seed=1))
        second = simulate_transactions(SimulationConfig(transaction_count=20, seed=2))

        self.assertNotEqual(first.records, second.records)

    def test_ids_are_unique_matched_and_customers_repeat(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(transaction_count=100, seed=42, customer_pool_size=10)
        )
        transaction_ids = [record.transaction.transaction_id for record in dataset.records]
        customer_ids = [record.transaction.customer_id for record in dataset.records]

        self.assertEqual(len(transaction_ids), len(set(transaction_ids)))
        self.assertEqual(transaction_ids[0], "SIM-000001")
        self.assertEqual(transaction_ids[-1], "SIM-000100")
        self.assertTrue(
            all(
                record.transaction.transaction_id == record.outcome.transaction_id
                for record in dataset.records
            )
        )
        self.assertLess(len(set(customer_ids)), len(customer_ids))

    def test_generated_domain_objects_and_money_are_valid(self) -> None:
        dataset = simulate_transactions(SimulationConfig(transaction_count=100, seed=9))

        for record in dataset.records:
            reparsed = parse_mobility_transaction(record.to_dict()["transaction"])
            self.assertEqual(reparsed.transaction_id, record.transaction.transaction_id)
            self.assertIsInstance(record.transaction.estimated_amount.amount_paise, int)
            self.assertIsInstance(record.outcome.actual_amount.amount_paise, int)
            self.assertGreater(record.transaction.estimated_amount.amount_paise, 0)
            self.assertGreater(record.outcome.actual_amount.amount_paise, 0)

    def test_actual_amount_is_not_a_context_field_or_exported_feature(self) -> None:
        record = simulate_transactions(
            SimulationConfig(transaction_count=1, seed=42)
        ).records[0]

        context_fields = {field.name for field in fields(RideTransactionContext)}
        self.assertNotIn("actual_amount", context_fields)
        self.assertNotIn("actual_amount_paise", record.to_dict()["transaction"])

    def test_timestamp_range_completion_order_and_timezone(self) -> None:
        config = SimulationConfig(transaction_count=100, seed=10)
        dataset = simulate_transactions(config)

        for record in dataset.records:
            timestamp = record.transaction.timestamp
            completed = record.outcome.completed_at
            self.assertGreaterEqual(timestamp, config.start_datetime)
            self.assertLessEqual(timestamp, config.end_datetime)
            self.assertGreater(completed, timestamp)
            self.assertIsNotNone(timestamp.utcoffset())
            self.assertIsNotNone(completed.utcoffset())

    def test_configurable_city_selection(self) -> None:
        config = SimulationConfig(
            transaction_count=100,
            seed=42,
            city_weights=((SupportedCity.MUMBAI, 1),),
        )

        dataset = simulate_transactions(config)

        self.assertEqual(
            {record.transaction.city for record in dataset.records},
            {SupportedCity.MUMBAI},
        )

    def test_city_profiles_influence_generated_rides(self) -> None:
        delhi = simulate_transactions(
            SimulationConfig(
                transaction_count=100,
                seed=42,
                city_weights=((SupportedCity.DELHI, 1),),
            )
        )
        bengaluru = simulate_transactions(
            SimulationConfig(
                transaction_count=100,
                seed=42,
                city_weights=((SupportedCity.BENGALURU, 1),),
            )
        )

        delhi_durations = tuple(
            record.transaction.estimated_duration_minutes for record in delhi.records
        )
        bengaluru_durations = tuple(
            record.transaction.estimated_duration_minutes
            for record in bengaluru.records
        )
        self.assertNotEqual(delhi_durations, bengaluru_durations)

    def test_fixed_seed_distribution_is_non_degenerate(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(
                transaction_count=1000, seed=42, customer_pool_size=100
            )
        )
        differences = [
            record.outcome.actual_amount.amount_paise
            - record.transaction.estimated_amount.amount_paise
            for record in dataset.records
        ]
        estimated = [
            record.transaction.estimated_amount.amount_paise
            for record in dataset.records
        ]

        self.assertTrue(any(value > 0 for value in differences))
        self.assertTrue(any(value < 0 for value in differences))
        self.assertTrue(
            any(
                abs(difference) <= max(1, int(Decimal(value) * Decimal("0.02")))
                for difference, value in zip(differences, estimated, strict=True)
            )
        )
        self.assertGreater(
            len({record.transaction.surge_multiplier for record in dataset.records}), 1
        )
        self.assertEqual(
            {record.transaction.city for record in dataset.records}, set(SupportedCity)
        )
        self.assertLess(
            len({record.transaction.customer_id for record in dataset.records}),
            len(dataset.records),
        )


if __name__ == "__main__":
    unittest.main()

