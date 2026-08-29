from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reserve_pay_optimizer.cli import main


class DynamicCliTests(unittest.TestCase):
    base_artifact = Path("artifacts/prediction/fare_distribution_v1")
    personalized_artifact = Path(
        "artifacts/prediction/fare_distribution_personalized_v1"
    )
    scenario = Path("examples/dynamic_reoptimization.json")

    def _run(self, arguments):
        output = StringIO()
        with redirect_stdout(output):
            status = main(arguments)
        return status, json.loads(output.getvalue())

    def _model_arguments(self):
        return [
            "--model",
            str(self.personalized_artifact),
            "--base-model",
            str(self.base_artifact),
        ]

    def test_dynamic_ride_recommends_without_mutation_when_not_confirmed(self):
        status, result = self._run(
            [
                "run-dynamic-ride",
                *self._model_arguments(),
                "--scenario",
                str(self.scenario),
                "--risk-profile",
                "balanced",
            ]
        )
        self.assertEqual(status, 0)
        self.assertFalse(result["auto_confirm"])
        self.assertFalse(result["payment_provider_called"])
        self.assertTrue(any(item["additional_block_required_paise"] > 0 for item in result["updates"]))
        self.assertEqual(
            result["final_authorized_block_paise"],
            result["initial"]["recommended_and_assumed_authorized_block_paise"],
        )
        self.assertFalse(any(item["simulated_authorization_confirmed"] for item in result["updates"]))

    def test_auto_confirm_demo_has_model_driven_increases_and_retrospective_outcome(self):
        status, result = self._run(
            [
                "run-dynamic-ride",
                *self._model_arguments(),
                "--scenario",
                str(self.scenario),
                "--risk-profile",
                "balanced",
                "--auto-confirm",
                "--verbose",
            ]
        )
        self.assertEqual(status, 0)
        blocks = [
            result["initial"]["recommended_and_assumed_authorized_block_paise"],
            *(item["authorized_block_after_event_paise"] for item in result["updates"]),
        ]
        self.assertEqual(blocks, sorted(blocks))
        self.assertFalse(result["retrospective_outcome"]["decision_time_use"])
        self.assertFalse(result["retrospective_outcome"]["static_initial_block_would_succeed"])
        self.assertTrue(result["retrospective_outcome"]["dynamic_final_block_would_succeed"])
        for item in result["updates"]:
            self.assertIn("previous_q97_paise", item["diagnostics"])
            self.assertIn("revised_q99_paise", item["diagnostics"])

    def test_simulation_and_static_dynamic_evaluation_workflow(self):
        with TemporaryDirectory() as temporary:
            dataset = Path(temporary) / "dynamic.json"
            status, simulation = self._run(
                [
                    "simulate-dynamic-mobility",
                    "--count",
                    "20",
                    "--seed",
                    "202608",
                    "--customer-pool-size",
                    "8",
                    "--personalized",
                    "--output",
                    str(dataset),
                ]
            )
            self.assertEqual(status, 0)
            self.assertFalse(simulation["hidden_simulator_values_exported"])
            status, evaluation = self._run(
                [
                    "evaluate-dynamic-reoptimization",
                    "--file",
                    str(dataset),
                    *self._model_arguments(),
                    "--risk-profile",
                    "balanced",
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(evaluation["record_count"], 20)
        self.assertIn("No real Razorpay authorization", evaluation["authorization_assumption"])
        self.assertEqual(evaluation["static"]["transaction_count"], 20)
        self.assertEqual(evaluation["dynamic"]["transaction_count"], 20)
        self.assertGreaterEqual(
            evaluation["dynamic_diagnostics"]["average_final_authorized_block_paise"],
            evaluation["dynamic_diagnostics"]["average_initial_block_paise"],
        )


if __name__ == "__main__":
    unittest.main()
