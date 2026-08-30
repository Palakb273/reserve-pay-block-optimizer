"""Phase-11 dashboard API contract and delegation tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from reserve_pay_optimizer.web.app import create_app
from reserve_pay_optimizer.web.evidence import prepare_dashboard_evidence
from reserve_pay_optimizer.web.services import DashboardSettings


ROOT = Path(__file__).resolve().parents[1]


class DashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        evidence_path = Path(cls._temporary.name) / "evidence.json"
        prepare_dashboard_evidence(count=30, seed=911, output=evidence_path)
        app = create_app(
            DashboardSettings(repository_root=ROOT, evidence_path=evidence_path)
        )
        cls._client_context = TestClient(app)
        cls.client = cls._client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_context.__exit__(None, None, None)
        cls._temporary.cleanup()

    @staticmethod
    def _request(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "transaction_id": "DASH-TEST-001",
            "estimated_amount_paise": 65000,
            "city": "hyderabad",
            "distance_km": "18.4",
            "estimated_duration_minutes": 42,
            "surge_multiplier": "1.18",
            "timestamp": "2027-01-15T18:30:00+05:30",
            "risk_profile": "balanced",
            "customer_profile": "stable_history",
        }
        payload.update(overrides)
        return payload

    def test_health_reports_models_loaded_and_phase_version(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok",
            "version": "0.12.0",
            "models_loaded": True,
        })

    def test_optimize_delegates_to_existing_financial_services(self) -> None:
        response = self.client.post("/api/optimize", json=self._request())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["transaction"]["estimated_amount_paise"], 65000)
        self.assertEqual(body["prediction"]["mode"], "personalized")
        self.assertEqual(set(body["prediction"]["quantiles_paise"]), {
            "0.05", "0.50", "0.90", "0.95", "0.97", "0.99"
        })
        self.assertGreater(body["decision"]["recommended_block_paise"], 0)
        self.assertEqual(body["meta"]["financial_logic_location"], "python_backend")

    def test_what_if_returns_recomputed_backend_differences(self) -> None:
        response = self.client.post(
            "/api/what-if",
            json={
                "base": self._request(),
                "overrides": {"traffic_level": "severe", "surge_multiplier": "1.35"},
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["revised"]["transaction"]["estimated_duration_minutes"], 65)
        expected_delta = (
            body["revised"]["decision"]["recommended_block_paise"]
            - body["previous"]["decision"]["recommended_block_paise"]
        )
        self.assertEqual(body["difference"]["recommended_block_paise"], expected_delta)

    def test_mock_authorization_is_separate_from_recommendation(self) -> None:
        response = self.client.post(
            "/api/mock/authorize",
            json={"transaction": self._request(), "idempotency_key": "dashboard-auth-1"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["execution"]["status"], "authorized")
        self.assertEqual(
            body["execution"]["authorized_amount_paise"],
            body["recommendation"]["decision"]["recommended_block_paise"],
        )

    def test_dynamic_failure_keeps_authorized_amount_visible(self) -> None:
        response = self.client.post(
            "/api/dynamic-demo",
            json={"risk_profile": "balanced", "fail_first_increase": True},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        failed_steps = [
            step for step in body["timeline"] if step["execution_status"] == "failed"
        ]
        self.assertTrue(failed_steps)
        failed = failed_steps[0]
        self.assertGreater(failed["recommended_target_paise"], failed["authorized_amount_paise"])
        first_authorized = body["timeline"][0]["authorized_amount_paise"]
        self.assertEqual(failed["authorized_amount_paise"], first_authorized)

    def test_precomputed_evidence_contains_provenance_and_three_strategies(self) -> None:
        response = self.client.get("/api/evidence")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provenance"]["record_count"], 30)
        self.assertEqual(set(body["strategies"]), {
            "exact_estimate", "fixed_buffer_20", "optimized_balanced"
        })
        self.assertIn("dataset_fingerprint_sha256", body["provenance"])

    def test_invalid_input_uses_structured_safe_error(self) -> None:
        response = self.client.post(
            "/api/optimize",
            json=self._request(estimated_amount_paise=0),
        )
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertTrue(body["error"]["details"])


if __name__ == "__main__":
    unittest.main()
