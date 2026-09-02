"""Phase-11 dashboard API contract and delegation tests."""

from __future__ import annotations

from pathlib import Path
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from reserve_pay_optimizer.config import (
    MAX_AMOUNT_PAISE,
    MAX_MOBILITY_DISTANCE_KM,
    MAX_MOBILITY_DURATION_MINUTES,
    MAX_MOBILITY_SURGE_MULTIPLIER,
)
from reserve_pay_optimizer.web.app import create_app
from reserve_pay_optimizer.web.services import DashboardService, DashboardSettings
from reserve_pay_optimizer.web.storage import InMemoryApplicationStore


ROOT = Path(__file__).resolve().parents[1]


class DashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        evidence_path = ROOT / "demo/evidence/final_evidence.json"
        app = create_app(
            DashboardSettings(repository_root=ROOT, evidence_path=evidence_path)
        )
        cls._client_context = TestClient(app)
        cls.client = cls._client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_context.__exit__(None, None, None)

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
            "version": "0.14.0",
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
        self.assertEqual(body["meta"]["data_mode"], "demo")
        self.assertTrue(body["meta"]["run_id"].startswith("opt_"))

        stored = self.client.get(f"/api/optimization-runs/{body['meta']['run_id']}")
        self.assertEqual(stored.status_code, 200)
        self.assertEqual(stored.json()["transaction_id"], "DASH-TEST-001")

    def test_readiness_exposes_storage_mode(self) -> None:
        response = self.client.get("/api/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ready",
                "data_mode": "demo",
                "storage_backend": "memory",
                "storage_ready": True,
                "models_loaded": True,
            },
        )

    def test_production_ride_ingest_is_not_exposed_in_demo(self) -> None:
        response = self.client.post(
            "/api/rides/completed",
            headers={"X-API-Key": "not-configured"},
            json={
                "transaction_id": "DASH-TEST-001",
                "customer_id": "C-REAL-001",
                "estimated_amount_paise": 65000,
                "actual_amount_paise": 70000,
                "city": "hyderabad",
                "distance_km": "18.4",
                "estimated_duration_minutes": 42,
                "surge_multiplier": "1.18",
                "timestamp": "2027-01-15T18:30:00+05:30",
                "completed_at": "2027-01-15T19:30:00+05:30",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "ingest_unauthorized")

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

    def test_authoritative_evidence_is_returned_without_metric_transformation(self) -> None:
        response = self.client.get("/api/evidence")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        source = json.loads(
            (ROOT / "demo/evidence/final_evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual(body, source)
        self.assertEqual(body["metadata"]["transaction_count"], 20_000)
        self.assertEqual(set(body["primary_strategy_comparison"]["metrics"]), {
            "exact_estimate", "fixed_buffer_20", "optimized_balanced"
        })
        self.assertIn("dataset_fingerprint_sha256", body["metadata"])

    def test_invalid_input_uses_structured_safe_error(self) -> None:
        response = self.client.post(
            "/api/optimize",
            json=self._request(estimated_amount_paise=0),
        )
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertTrue(body["error"]["details"])

    def test_financial_paise_fields_require_actual_json_integers(self) -> None:
        for invalid in (True, False, "65000", 65_000.5):
            with self.subTest(value=invalid):
                response = self.client.post(
                    "/api/optimize",
                    json=self._request(estimated_amount_paise=invalid),
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")

        accepted = self.client.post(
            "/api/optimize", json=self._request(estimated_amount_paise=65_000)
        )
        self.assertEqual(accepted.status_code, 200)

        oversized = self.client.post(
            "/api/optimize",
            json=self._request(estimated_amount_paise=MAX_AMOUNT_PAISE + 1),
        )
        self.assertEqual(oversized.status_code, 422)

    def test_extreme_ride_numbers_are_structured_validation_errors(self) -> None:
        cases = {
            "distance_km": str(MAX_MOBILITY_DISTANCE_KM + 1),
            "estimated_duration_minutes": MAX_MOBILITY_DURATION_MINUTES + 1,
            "surge_multiplier": str(MAX_MOBILITY_SURGE_MULTIPLIER + 1),
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                response = self.client.post(
                    "/api/optimize", json=self._request(**{field: value})
                )
                self.assertEqual(response.status_code, 422)
                body = response.json()
                self.assertEqual(body["error"]["code"], "invalid_request")
                self.assertNotIn("Traceback", response.text)

    def test_ingestion_key_accepts_valid_rejects_invalid_and_never_leaks(self) -> None:
        secret = "security-test-ingestion-key-1234567890"
        settings = DashboardSettings(
            repository_root=ROOT,
            data_mode="mongodb",
            mongodb_uri="unused-with-in-memory-test-store",
            ingest_api_key=secret,
        )
        service = DashboardService(settings, store=InMemoryApplicationStore())
        ride = {
            "transaction_id": "SECURITY-INGEST-001",
            "customer_id": "C-SECURITY-001",
            "estimated_amount_paise": 65_000,
            "actual_amount_paise": 70_000,
            "city": "hyderabad",
            "distance_km": "18.4",
            "estimated_duration_minutes": 42,
            "surge_multiplier": "1.18",
            "timestamp": "2027-01-15T18:30:00+05:30",
            "completed_at": "2027-01-15T19:30:00+05:30",
        }
        with patch(
            "reserve_pay_optimizer.web.app.DashboardService", return_value=service
        ):
            with TestClient(create_app(settings)) as client:
                invalid = client.post(
                    "/api/rides/completed",
                    headers={"X-API-Key": "incorrect"},
                    json=ride,
                )
                boolean_actual = client.post(
                    "/api/rides/completed",
                    headers={"X-API-Key": secret},
                    json={**ride, "actual_amount_paise": True},
                )
                string_estimate = client.post(
                    "/api/rides/completed",
                    headers={"X-API-Key": secret},
                    json={**ride, "estimated_amount_paise": "65000"},
                )
                valid = client.post(
                    "/api/rides/completed",
                    headers={"X-API-Key": secret},
                    json=ride,
                )
                replay = client.post(
                    "/api/rides/completed",
                    headers={"X-API-Key": secret},
                    json=ride,
                )
                health = client.get("/api/health")

        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(boolean_actual.status_code, 422)
        self.assertEqual(string_estimate.status_code, 422)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["status"], "created")
        self.assertEqual(replay.json()["status"], "replayed")
        for response in (
            invalid,
            boolean_actual,
            string_estimate,
            valid,
            replay,
            health,
        ):
            self.assertNotIn(secret, response.text)


if __name__ == "__main__":
    unittest.main()
