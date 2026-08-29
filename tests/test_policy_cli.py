from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reserve_pay_optimizer.cli import main
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class PolicyCliTests(unittest.TestCase):
    artifact = Path("artifacts/prediction/fare_distribution_v1")
    example = Path("examples/valid_hyderabad_ride.json")

    def _run_json(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        stream = StringIO()
        with redirect_stdout(stream):
            status = main(arguments)
        return status, json.loads(stream.getvalue())

    def test_single_transaction_cli_supports_each_profile(self) -> None:
        for profile, target in (
            ("aggressive", "0.930000"),
            ("balanced", "0.970000"),
            ("conservative", "0.990000"),
        ):
            with self.subTest(profile=profile):
                status, result = self._run_json(
                    [
                        "optimize-block",
                        "--model",
                        str(self.artifact),
                        "--file",
                        str(self.example),
                        "--risk-profile",
                        profile,
                    ]
                )
                self.assertEqual(status, 0)
                self.assertEqual(result["risk_profile"], profile)
                self.assertEqual(result["target_collection_probability"], target)
                self.assertTrue(result["policy_satisfied"])
                self.assertNotIn("actual_amount_paise", result)

    def test_compare_and_evaluate_profile_workflows(self) -> None:
        status, comparison = self._run_json(
            [
                "compare-risk-profiles",
                "--model",
                str(self.artifact),
                "--file",
                str(self.example),
            ]
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            set(comparison["profiles"]),
            {"aggressive", "balanced", "conservative"},
        )

        dataset = simulate_transactions(
            SimulationConfig(transaction_count=21, seed=608, customer_pool_size=7)
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "unseen.json"
            path.write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
            status, evaluation = self._run_json(
                [
                    "evaluate-risk-profiles",
                    "--model",
                    str(self.artifact),
                    "--file",
                    str(path),
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(
            set(evaluation["strategies"]),
            {
                "exact_estimate",
                "fixed_buffer_20",
                "optimized_aggressive",
                "optimized_balanced",
                "optimized_conservative",
            },
        )
        self.assertEqual(
            set(evaluation["risk_profile_diagnostics"]),
            {"aggressive", "balanced", "conservative"},
        )
        self.assertTrue(
            all(
                metrics["transaction_count"] == 21
                for metrics in evaluation["strategies"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
