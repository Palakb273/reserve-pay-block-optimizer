from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reserve_pay_optimizer.cli import main
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class PersonalizationCliTests(unittest.TestCase):
    base_artifact = Path("artifacts/prediction/fare_distribution_v1")
    personalized_artifact = Path(
        "artifacts/prediction/fare_distribution_personalized_v1"
    )
    scenario_path = Path("examples/personalization_comparison.json")

    def _run(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        output = StringIO()
        with redirect_stdout(output):
            status = main(arguments)
        return status, json.loads(output.getvalue())

    def test_prediction_and_optimization_choose_personalized_mode(self) -> None:
        scenario = json.loads(self.scenario_path.read_text(encoding="utf-8"))
        customer = scenario["customers"][0]
        with TemporaryDirectory() as temporary:
            current = Path(temporary) / "current.json"
            history = Path(temporary) / "history.json"
            current.write_text(json.dumps(customer["transaction"]), encoding="utf-8")
            history.write_text(json.dumps(customer["history"]), encoding="utf-8")
            common = [
                "--model", str(self.personalized_artifact),
                "--base-model", str(self.base_artifact),
                "--history", str(history),
                "--file", str(current),
            ]
            status, prediction = self._run(
                ["predict-personalized-distribution", *common]
            )
            self.assertEqual(status, 0)
            self.assertEqual(prediction["prediction_mode"], "personalized")
            self.assertEqual(prediction["history_count"], 8)
            self.assertNotIn("actual_amount_paise", prediction)
            status, optimization = self._run(
                ["optimize-personalized-block", *common, "--risk-profile", "balanced"]
            )
            self.assertEqual(status, 0)
            self.assertEqual(optimization["prediction_mode"], "personalized")
            self.assertTrue(optimization["policy_satisfied"])

    def test_customer_comparison_uses_calculated_history_and_model_outputs(self) -> None:
        status, result = self._run(
            [
                "compare-customer-personalization",
                "--model", str(self.personalized_artifact),
                "--base-model", str(self.base_artifact),
                "--scenario", str(self.scenario_path),
                "--risk-profile", "balanced",
            ]
        )
        self.assertEqual(status, 0)
        stable = result["customers"]["stable_history_customer"]
        overrun = result["customers"]["overrun_prone_history_customer"]
        self.assertGreater(overrun["q97_paise"], stable["q97_paise"])
        self.assertGreater(
            overrun["recommended_block_paise"], stable["recommended_block_paise"]
        )

    def test_external_chronological_evaluation_cli(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(
                transaction_count=80,
                seed=712,
                customer_pool_size=8,
                customer_behavior_enabled=True,
            )
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "external.json"
            path.write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
            status, result = self._run(
                [
                    "evaluate-personalization",
                    "--file", str(path),
                    "--model", str(self.personalized_artifact),
                    "--base-model", str(self.base_artifact),
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(result["evaluation_scope"], "chronological_test_split")
        self.assertEqual(result["test_records"], 12)
        self.assertIn("downstream_balanced_policy", result)


if __name__ == "__main__":
    unittest.main()
