from decimal import Decimal
import unittest

from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.evaluation_input import parse_evaluation_dataset
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.diagnostics import summarize_simulation
from reserve_pay_optimizer.simulation.generator import simulate_transactions
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy


class SimulationIntegrationTests(unittest.TestCase):
    def test_export_plugs_directly_into_phase_2_comparison(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(transaction_count=200, seed=42, customer_pool_size=30)
        )

        transactions, outcomes = parse_evaluation_dataset(dataset.to_dict())
        comparison = compare_strategies(
            transactions,
            outcomes,
            (ExactEstimateStrategy(), FixedBufferStrategy()),
        )

        self.assertEqual(comparison.transaction_ids, tuple(
            record.transaction.transaction_id for record in dataset.records
        ))
        self.assertEqual(
            {metrics.strategy for metrics in comparison.metrics},
            {"exact_estimate", "fixed_buffer_20"},
        )
        self.assertTrue(all(metrics.transaction_count == 200 for metrics in comparison.metrics))

    def test_diagnostics_describe_generated_records(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(transaction_count=1000, seed=42, customer_pool_size=100)
        )

        diagnostics = summarize_simulation(dataset.records)

        self.assertEqual(diagnostics.transaction_count, 1000)
        self.assertEqual(diagnostics.unique_customer_count, 100)
        self.assertEqual(sum(dict(diagnostics.city_counts).values()), 1000)
        self.assertGreater(diagnostics.average_estimated_amount.amount_paise, 0)
        self.assertGreater(diagnostics.average_actual_amount.amount_paise, 0)
        self.assertGreater(diagnostics.actual_above_estimate_rate, Decimal(0))
        self.assertGreater(diagnostics.actual_below_estimate_rate, Decimal(0))
        self.assertGreater(diagnostics.actual_near_estimate_rate, Decimal(0))
        self.assertGreater(diagnostics.surge_frequency, Decimal(0))


if __name__ == "__main__":
    unittest.main()
