from datetime import timedelta
import unittest

from reserve_pay_optimizer.personalization.dataset import (
    build_personalized_records,
    chronological_split,
)
from reserve_pay_optimizer.prediction.config import ModelConfig
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions
from tests.personalization_fixtures import BASE_TIME, context_at, outcome_at


class PersonalizedDatasetTests(unittest.TestCase):
    def test_completion_queue_prevents_overlapping_and_equal_time_leakage(self) -> None:
        contexts = (
            context_at("A", "C-A", BASE_TIME, 10000),
            context_at("B", "C-A", BASE_TIME + timedelta(minutes=30), 10000),
            context_at("C", "C-A", BASE_TIME + timedelta(hours=1), 10000),
            context_at("D", "C-A", BASE_TIME + timedelta(hours=1, seconds=1), 10000),
        )
        outcomes = (
            outcome_at("A", BASE_TIME + timedelta(hours=1), 11000),
            outcome_at("B", BASE_TIME + timedelta(hours=2), 12000),
            outcome_at("C", BASE_TIME + timedelta(hours=2), 10000),
            outcome_at("D", BASE_TIME + timedelta(hours=2), 10000),
        )
        records = build_personalized_records(contexts, outcomes)
        counts = {record.context.transaction_id: record.history.completed_ride_count for record in records}
        self.assertEqual(counts, {"A": 0, "B": 0, "C": 0, "D": 1})

    def test_chronological_split_is_ordered_disjoint_and_complete(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(
                transaction_count=40,
                seed=707,
                customer_pool_size=5,
                customer_behavior_enabled=True,
            )
        )
        records = build_personalized_records(dataset.transactions, dataset.outcomes)
        split = chronological_split(records, ModelConfig(seed=999))
        combined = (*split.train, *split.validation, *split.test)
        self.assertEqual(len(combined), 40)
        self.assertEqual(len({item.context.transaction_id for item in combined}), 40)
        timestamps = [item.context.timestamp for item in combined]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertLessEqual(split.train[-1].context.timestamp, split.validation[0].context.timestamp)
        self.assertLessEqual(split.validation[-1].context.timestamp, split.test[0].context.timestamp)

    def test_opt_in_simulator_is_reproducible_and_hidden_profiles_never_export(self) -> None:
        config = SimulationConfig(
            transaction_count=300,
            seed=708,
            customer_pool_size=8,
            customer_behavior_enabled=True,
        )
        first = simulate_transactions(config)
        second = simulate_transactions(config)
        self.assertEqual(first.to_dict(), second.to_dict())
        serialized = first.to_dict()
        self.assertIn("customer_behavior", serialized["metadata"])
        for record in serialized["records"]:
            transaction = record["transaction"]
            self.assertNotIn("customer_overrun_bias", transaction)
            self.assertNotIn("customer_variance_multiplier", transaction)
            self.assertNotIn("customer_behavior", transaction)


if __name__ == "__main__":
    unittest.main()

