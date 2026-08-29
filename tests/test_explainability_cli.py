from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import unittest

from reserve_pay_optimizer.cli import main


class ExplainabilityCliTests(unittest.TestCase):
    base_model = Path("artifacts/prediction/fare_distribution_v1")
    model = Path("artifacts/prediction/fare_distribution_personalized_v1")

    def run_cli(self, arguments):
        output = StringIO()
        with redirect_stdout(output):
            status = main(arguments)
        return status, json.loads(output.getvalue())

    def models(self):
        return ["--model", str(self.model), "--base-model", str(self.base_model)]

    def test_explain_block_proves_balanced_minimum_can_select_q99(self):
        status, result = self.run_cli(
            [
                "explain-block",
                *self.models(),
                "--history",
                "examples/personalization_stable_history.json",
                "--file",
                "examples/personalization_current_ride.json",
                "--risk-profile",
                "balanced",
                "--detail",
                "detailed",
            ]
        )
        self.assertEqual(status, 0)
        facts = result["explanation"]["facts"]
        self.assertEqual(
            facts["recommended_block_paise"],
            result["decision"]["recommended_block_paise"],
        )
        self.assertEqual(facts["risk_policy"]["target_collection_probability"], "0.970000")
        self.assertEqual(facts["estimated_collection_probability"], "0.990000")
        self.assertGreater(
            facts["recommended_block_paise"],
            facts["prediction_quantiles_paise"]["0.97"],
        )
        self.assertEqual(
            facts["recommended_block_paise"],
            facts["prediction_quantiles_paise"]["0.99"],
        )
        self.assertIn("minimum feasibility requirement", result["explanation"]["text"])
        self.assertTrue(any(item["selected"] for item in facts["candidate_comparison"]))

    def test_dynamic_run_explanations_preserve_additional_and_authorization_facts(self):
        status, result = self.run_cli(
            [
                "run-dynamic-ride",
                *self.models(),
                "--scenario",
                "examples/dynamic_reoptimization.json",
                "--risk-profile",
                "balanced",
                "--auto-confirm",
                "--explain",
                "--detail",
                "detailed",
            ]
        )
        self.assertEqual(status, 0)
        self.assertEqual(result["explanation_validation_metrics"]["explanations_generated"], 2)
        for update in result["updates"]:
            explanation = update["explanation"]
            dynamic = explanation["facts"]["dynamic_context"]
            self.assertEqual(
                dynamic["additional_block_required_paise"],
                update["additional_block_required_paise"],
            )
            self.assertEqual(dynamic["authorization_status"], "simulated_confirmed")
            self.assertIn("previous_quantiles", dynamic)
            self.assertIn("revised_quantiles", dynamic)
            self.assertNotIn("actual_amount", json.dumps(explanation).casefold())


if __name__ == "__main__":
    unittest.main()
