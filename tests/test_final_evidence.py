"""Phase-13 deterministic evidence and statistical-contract tests."""

from __future__ import annotations

from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from reserve_pay_optimizer.cli import main
from reserve_pay_optimizer.evidence.config import FinalEvidenceConfig
from reserve_pay_optimizer.evidence.datasets import dataset_fingerprint, generate_dataset
from reserve_pay_optimizer.evidence.pipeline import validate_final_evidence
from reserve_pay_optimizer.evidence.fingerprint import evidence_fingerprint
from reserve_pay_optimizer.evidence.statistics import bootstrap_mean_paise, wilson_ci
from reserve_pay_optimizer.prediction.config import QUANTILES

ROOT = Path(__file__).resolve().parents[1]


class FinalEvidenceConfigTests(unittest.TestCase):
    def test_authoritative_defaults_are_valid(self) -> None:
        config = FinalEvidenceConfig()
        self.assertGreaterEqual(config.transaction_count, 10_000)
        self.assertEqual(config.primary_risk_profile, "balanced")

    def test_too_small_authoritative_dataset_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least|10,000|>="):
            FinalEvidenceConfig(transaction_count=9_999)

    def test_invalid_cohort_and_profile_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dynamic_record_count"):
            FinalEvidenceConfig(dynamic_record_count=20_001)
        with self.assertRaisesRegex(ValueError, "risk profile"):
            FinalEvidenceConfig(primary_risk_profile="invented")


class EvidenceDatasetTests(unittest.TestCase):
    def test_dataset_and_fingerprint_are_seeded_and_deterministic(self) -> None:
        first = generate_dataset(count=8, seed=881, customer_pool_size=4)
        second = generate_dataset(count=8, seed=881, customer_pool_size=4)
        different = generate_dataset(count=8, seed=882, customer_pool_size=4)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(dataset_fingerprint(first), dataset_fingerprint(second))
        self.assertNotEqual(dataset_fingerprint(first), dataset_fingerprint(different))


class EvidenceStatisticsTests(unittest.TestCase):
    def test_wilson_interval_matches_hand_check(self) -> None:
        interval = wilson_ci(50, 100)
        self.assertEqual(interval["point_estimate"], "0.500000")
        self.assertEqual(interval["lower"], "0.403832")
        self.assertEqual(interval["upper"], "0.596168")
        self.assertEqual(interval["method"], "wilson_score")

    def test_wilson_rejects_invalid_counts_and_unsupported_confidence(self) -> None:
        with self.assertRaises(ValueError):
            wilson_ci(2, 1)
        with self.assertRaises(ValueError):
            wilson_ci(1, 2, Decimal("0.90"))

    def test_bootstrap_is_seeded_without_mutating_global_rng(self) -> None:
        values = (100, 200, 300, 400)
        first = bootstrap_mean_paise(values, seed=42, samples=100)
        second = bootstrap_mean_paise(values, seed=42, samples=100)
        self.assertEqual(first, second)
        random.seed(991)
        expected = random.random()
        random.seed(991)
        bootstrap_mean_paise(values, seed=42, samples=10)
        self.assertEqual(random.random(), expected)


class FinalEvidenceContractTests(unittest.TestCase):
    def _artifact(self, config: FinalEvidenceConfig) -> dict[str, object]:
        metrics = {
            key: {
                "transaction_count": config.transaction_count,
                "collection_success_rate": "0.900000",
                "under_block_rate": "0.100000",
                "capital_efficiency": "0.900000",
                "average_excess_block_ratio": "0.100000",
            }
            for key in ("exact_estimate", "fixed_buffer_20", "optimized_balanced")
        }
        cities = {
            city: {"record_count": 1}
            for city in (
                "delhi",
                "mumbai",
                "bengaluru",
                "hyderabad",
                "pune",
                "chennai",
                "kolkata",
            )
        }
        artifact = {
            "metadata": {
                "evidence_status": "complete",
                "record_count": config.transaction_count,
                "dataset_fingerprint_sha256": "a" * 64,
                "evidence_fingerprint_sha256": "",
                "retraining_performed": False,
                "evaluation_dataset_used_for_training": False,
                "base_model": {"trusted_sources_only": True, "model_version": "base-v1"},
                "personalized_model": {"trusted_sources_only": True, "model_version": "personal-v1"},
            },
            "primary_strategy_comparison": {
                "metrics": metrics,
                "confidence_intervals_95": {key: {} for key in metrics},
            },
            "prediction": {
                "record_count": config.transaction_count,
                "quantiles": {
                    f"{value:.2f}": {"observed_coverage": "0.900000"}
                    for value in QUANTILES
                },
            },
            "personalization": {
                "test_records": config.transaction_count,
                "minimum_personalization_history": 3,
                "history_depth": {key: {} for key in ("0-2", "3-5", "6-10", "11+")},
                "observed_history_segments": {"historically_stable": {}},
            },
            "risk_profiles": {
                "profiles": {key: {} for key in ("aggressive", "balanced", "conservative")},
                "collapse_diagnostics": {
                    "record_count": config.transaction_count,
                    "all_three_same_count": config.transaction_count,
                    "exactly_two_same_count": 0,
                    "all_distinct_count": 0,
                },
            },
            "dynamic": {
                "record_count": config.dynamic_record_count,
                "benefit_categories": {
                    "static_failed_dynamic_succeeded": 0,
                    "both_succeeded": config.dynamic_record_count,
                    "both_failed": 0,
                    "static_succeeded_dynamic_failed": 0,
                },
            },
            "cities": cities,
            "agents": {
                "total_records": config.agent_record_count,
                "failed_runs": 0,
                "decision_mismatches": 0,
                "equivalence_rate": "1.000000",
            },
            "explainability": {
                "record_count": config.agent_record_count,
                "numeric_consistency_mismatches": 0,
                "privacy_violations": 0,
            },
            "reserve_pay_mock_validation": {
                "total_scenarios": 11,
                "passed_scenarios": 11,
                "failed_scenarios": 0,
            },
            "limitations": ["synthetic"] * 5,
        }
        artifact["metadata"]["evidence_fingerprint_sha256"] = evidence_fingerprint(artifact)
        return artifact

    def test_complete_artifact_contract_accepts_all_required_evidence(self) -> None:
        config = FinalEvidenceConfig()
        validate_final_evidence(self._artifact(config), config)

    def test_missing_quantile_or_agent_mismatch_fails_closed(self) -> None:
        config = FinalEvidenceConfig()
        artifact = self._artifact(config)
        calibration = artifact["prediction"]
        assert isinstance(calibration, dict) and isinstance(calibration["quantiles"], dict)
        calibration["quantiles"].pop("0.97")
        with self.assertRaisesRegex(ValueError, "quantile"):
            validate_final_evidence(artifact, config)
        artifact = self._artifact(config)
        agent = artifact["agents"]
        assert isinstance(agent, dict)
        agent["decision_mismatches"] = 1
        with self.assertRaisesRegex(ValueError, "Agent|agent"):
            validate_final_evidence(artifact, config)

    def test_cli_exposes_authoritative_evidence_workflow(self) -> None:
        artifact = self._artifact(FinalEvidenceConfig())
        with tempfile.TemporaryDirectory() as temporary, patch(
            "reserve_pay_optimizer.evidence.generate_final_evidence",
            return_value=artifact,
        ) as generator:
            output = Path(temporary) / "evidence.json"
            stream = StringIO()
            with redirect_stdout(stream):
                status = main(["prepare-final-evidence", "--output", str(output)])
        self.assertEqual(status, 0)
        self.assertIn('"evidence_status": "complete"', stream.getvalue())
        generator.assert_called_once()

    def test_checked_in_artifact_is_authoritative_and_dashboard_ready(self) -> None:
        import json

        config = FinalEvidenceConfig()
        artifact = json.loads(
            (ROOT / "demo/evidence/final_evidence.json").read_text(encoding="utf-8")
        )
        validate_final_evidence(artifact, config)
        self.assertEqual(artifact["metadata"]["project_version"], "0.14.0")
        self.assertEqual(artifact["metadata"]["record_count"], 20_000)
        self.assertEqual(artifact["prediction"]["record_count"], 20_000)
        self.assertEqual(artifact["agents"]["decision_mismatches"], 0)
        self.assertTrue(
            {
                "primary_strategy_comparison",
                "risk_profiles",
                "personalization",
                "dynamic",
            }.issubset(artifact)
        )


if __name__ == "__main__":
    unittest.main()
