import unittest

from reserve_pay_optimizer.dynamic.serialization import parse_dynamic_dataset
from reserve_pay_optimizer.dynamic.simulation import simulate_dynamic_transactions
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class DynamicSimulationTests(unittest.TestCase):
    def test_same_seed_is_reproducible_and_round_trips(self):
        config = SimulationConfig(
            transaction_count=30,
            seed=202608,
            customer_pool_size=8,
            customer_behavior_enabled=True,
        )
        first = simulate_dynamic_transactions(config).to_dict()
        second = simulate_dynamic_transactions(config).to_dict()
        self.assertEqual(first, second)
        parsed = parse_dynamic_dataset(first)
        self.assertEqual(parsed.to_dict(), first)

    def test_updates_are_ordered_inside_active_ride_and_export_no_hidden_values(self):
        dataset = simulate_dynamic_transactions(
            SimulationConfig(transaction_count=50, seed=9)
        )
        self.assertTrue(any(record.updates for record in dataset.records))
        for record in dataset.records:
            for index, update in enumerate(record.updates, start=1):
                self.assertEqual(update.sequence_number, index)
                self.assertGreater(update.observed_at, record.initial_transaction.timestamp)
                self.assertLess(update.observed_at, record.outcome.completed_at)
        serialized = str(dataset.to_dict()).casefold()
        for forbidden in (
            "pricing_noise",
            "traffic_change_ratio",
            "route_change_ratio",
            "customer_overrun_bias",
            "customer_variance_multiplier",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_existing_simulator_output_is_unchanged_by_dynamic_generation(self):
        config = SimulationConfig(transaction_count=20, seed=42)
        before = simulate_transactions(config).to_dict()
        simulate_dynamic_transactions(config)
        after = simulate_transactions(config).to_dict()
        self.assertEqual(before, after)

