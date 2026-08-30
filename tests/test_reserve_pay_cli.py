from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from reserve_pay_optimizer.cli import main


class ReservePayCliTests(unittest.TestCase):
    base_model = Path("artifacts/prediction/fare_distribution_v1")
    model = Path("artifacts/prediction/fare_distribution_personalized_v1")
    scenario = Path("examples/dynamic_reoptimization.json")

    def run_cli(self, *extra):
        output = StringIO()
        with redirect_stdout(output):
            status = main(
                [
                    "reserve-pay-demo",
                    "--provider",
                    "mock",
                    "--model",
                    str(self.model),
                    "--base-model",
                    str(self.base_model),
                    "--scenario",
                    str(self.scenario),
                    *extra,
                ]
            )
        return status, json.loads(output.getvalue())

    def test_complete_mock_demo_uses_calculated_values(self):
        status, result = self.run_cli("--explain", "--verbose")
        self.assertEqual(status, 0)
        self.assertEqual(result["provider"], "mock")
        self.assertEqual(result["initial"]["execution"]["status"], "authorized")
        self.assertTrue(
            all(item["execution"]["execution_status"] == "succeeded" for item in result["updates"])
        )
        self.assertEqual(result["completion"]["status"], "settled")
        self.assertEqual(result["final_block_status"]["status"], "released")
        self.assertEqual(
            result["completion"]["debited_amount_paise"],
            result["completion"]["final_amount_paise"],
        )
        self.assertFalse(result["actual_amount_decision_time_use"])
        self.assertIn("explanation", result["initial"])

    def test_failure_demo_preserves_prior_authorization(self):
        status, result = self.run_cli("--fail-first-increase")
        self.assertEqual(status, 0)
        first = result["updates"][0]
        self.assertEqual(first["execution"]["execution_status"], "failed")
        self.assertEqual(
            first["execution"]["authorized_block_after_execution_paise"],
            result["initial"]["execution"]["authorized_amount_paise"],
        )
        self.assertGreater(
            first["execution"]["recommended_target_block_paise"],
            first["execution"]["authorized_block_after_execution_paise"],
        )

    def test_retry_demo_reuses_one_key(self):
        status, result = self.run_cli("--retry-first-increase", "--verbose")
        self.assertEqual(status, 0)
        attempts = [
            item
            for item in result["provider_attempts"]
            if item["operation"] == "increase"
        ]
        self.assertGreaterEqual(len(attempts), 3)
        self.assertEqual(attempts[0]["idempotency_key"], attempts[1]["idempotency_key"])
        self.assertEqual(result["updates"][0]["execution"]["execution_status"], "succeeded")

    def test_razorpay_selection_never_falls_back_to_mock(self):
        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            status = main(
                [
                    "reserve-pay-demo",
                    "--provider",
                    "razorpay",
                    "--model",
                    str(self.model),
                    "--base-model",
                    str(self.base_model),
                    "--scenario",
                    str(self.scenario),
                ]
            )
        result = json.loads(output.getvalue())
        self.assertEqual(status, 2)
        self.assertEqual(result["code"], "provider_configuration_error")
        self.assertNotIn("mock", json.dumps(result).casefold())


if __name__ == "__main__":
    unittest.main()
