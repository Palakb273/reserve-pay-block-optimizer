from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reserve_pay_optimizer.cli import main
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class OptimizerCliTests(unittest.TestCase):
    artifact = Path("artifacts/prediction/fare_distribution_v1")

    def test_single_transaction_optimization_cli(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            status = main(
                [
                    "optimize-block",
                    "--model", str(self.artifact),
                    "--file", "examples/valid_hyderabad_ride.json",
                    "--verbose",
                ]
            )
        result = json.loads(stream.getvalue())
        self.assertEqual(status, 0)
        self.assertGreater(result["recommended_block_paise"], 0)
        self.assertLessEqual(Decimal(result["estimated_collection_probability"]), Decimal("0.99"))
        self.assertEqual(len(result["best_candidate_scores"]), 5)
        self.assertNotIn("actual_amount_paise", result)

    def test_unseen_simulator_dataset_runs_all_strategies_through_cli(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(transaction_count=30, seed=98765, customer_pool_size=10)
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "unseen.json"
            path.write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
            stream = StringIO()
            with redirect_stdout(stream):
                status = main(
                    [
                        "evaluate-optimizer",
                        "--model", str(self.artifact),
                        "--file", str(path),
                    ]
                )
        result = json.loads(stream.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(
            set(result["strategies"]),
            {"exact_estimate", "fixed_buffer_20", "optimized_reserve"},
        )
        self.assertTrue(all(value["transaction_count"] == 30 for value in result["strategies"].values()))
        self.assertGreater(result["optimizer_diagnostics"]["average_recommended_block_paise"], 0)


if __name__ == "__main__":
    unittest.main()
