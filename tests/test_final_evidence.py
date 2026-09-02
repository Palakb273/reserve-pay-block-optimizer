"""Phase-13 deterministic evidence and statistical-contract tests."""

from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
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
from reserve_pay_optimizer.evidence.errors import EvidenceValidationError
from reserve_pay_optimizer.evidence.mock_validation import validate_mock_reserve_pay
from reserve_pay_optimizer.evidence.reporting import render_evidence_markdown
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
                "average_excess_block_paise": 100,
                "average_under_block_paise": 10,
                "average_block_amount_paise": 1_000,
                "collection_success_count": config.transaction_count,
                "under_block_count": 0,
                "total_actual_amount_paise": config.transaction_count * 900,
                "total_blocked_amount_paise": config.transaction_count * 1_000,
                "strategy": key,
            }
            for key in ("exact_estimate", "fixed_buffer_20", "optimized_balanced")
        }
        city_names = (
                "delhi",
                "mumbai",
                "bengaluru",
                "hyderabad",
                "pune",
                "chennai",
                "kolkata",
        )
        cities = {
            city: {
                "record_count": config.transaction_count // len(city_names) + (index < config.transaction_count % len(city_names)),
                "optimized_collection_success_rate": "0.900000",
                "optimized_average_excess_block_paise": 100,
                "strategies": {},
            }
            for index, city in enumerate(city_names)
        }
        predictor_metrics = {
            "record_count": config.transaction_count,
            "mean_pinball_loss_paise": "1.000000",
            "median_mae_paise": "1.000000",
            "quantiles": {},
            "prediction_interval_q05_q95": {},
            "raw_quantile_crossing": {},
            "per_city": {},
        }
        risk_profile = {
            "target_collection_probability": "0.900000",
            "realized_collection_success": "0.900000",
            "under_block_rate": "0.100000",
            "average_block_paise": 1_000,
            "average_excess_paise": 100,
            "capital_efficiency": "0.900000",
            "policy_satisfaction_rate": "1.000000",
            "realized_minus_target": "0.000000",
            "metrics": {},
        }
        dynamic_metrics = {
            "transaction_count": config.dynamic_record_count,
            "collection_success_rate": "1.000000",
            "under_block_rate": "0.000000",
            "average_excess_block_paise": 100,
            "average_under_block_paise": 0,
            "average_excess_block_ratio": "0.100000",
            "capital_efficiency": "0.900000",
        }
        artifact = {
            "metadata": {
                "evidence_status": "complete",
                "record_count": config.transaction_count,
                "dataset_seed": config.dataset_seed,
                "transaction_count": config.transaction_count,
                "customer_pool_size": config.customer_pool_size,
                "dataset_fingerprint_sha256": "a" * 64,
                "dataset_fingerprint": "a" * 64,
                "evidence_fingerprint_sha256": "",
                "evidence_fingerprint": "",
                "retraining_performed": False,
                "models_retrained": False,
                "evaluation_dataset_used_for_training": False,
                "base_model_version": "base-v1",
                "personalized_model_version": "personal-v1",
                "primary_strategy": "optimized_balanced",
                "primary_risk_profile": "balanced",
                "dynamic_seed": config.dynamic_seed,
                "dynamic_record_count": config.dynamic_record_count,
                "agent_record_count": config.agent_record_count,
                "bootstrap_seed": config.bootstrap_seed,
                "bootstrap_samples": config.bootstrap_samples,
                "base_model": {"trusted_sources_only": True, "model_version": "base-v1"},
                "personalized_model": {"trusted_sources_only": True, "model_version": "personal-v1"},
            },
            "primary_strategy_comparison": {
                "metrics": metrics,
                "confidence_intervals_95": {key: {} for key in metrics},
            },
            "prediction": {
                **predictor_metrics,
                "quantiles": {
                    f"{value:.2f}": {
                        "target_coverage": f"{value:.6f}",
                        "observed_coverage": "0.900000",
                        "calibration_error": "0.000000",
                        "absolute_calibration_error": "0.000000",
                        "pinball_loss_paise": "1.000000",
                    }
                    for value in QUANTILES
                },
            },
            "personalization": {
                "test_records": config.transaction_count,
                "eligible_record_count": config.transaction_count,
                "minimum_personalization_history": 3,
                "fallback_record_count": config.transaction_count,
                "fallback_percentage": "1.000000",
                "personalized_record_count": 0,
                "personalized_percentage": "0.000000",
                "base_predictor": predictor_metrics,
                "personalized_predictor": predictor_metrics,
                "comparison": {},
                "history_depth": {key: {} for key in ("0-2", "3-5", "6-10", "11+")},
                "observed_history_segments": {"historically_stable": {}},
                "downstream_balanced_policy": {},
                "same_ride_history_demo": {},
            },
            "risk_profiles": {
                "profiles": {key: risk_profile for key in ("aggressive", "balanced", "conservative")},
                "collapse_analysis": {
                    "record_count": config.transaction_count,
                    "all_three_same_count": config.transaction_count,
                    "exactly_two_same_count": 0,
                    "all_three_distinct_count": 0,
                    "all_three_same_rate": "1.000000",
                    "exactly_two_same_rate": "0.000000",
                    "at_least_two_differ_count": 0,
                    "at_least_two_differ_rate": "0.000000",
                    "all_three_distinct_rate": "0.000000",
                    "aggressive_equals_balanced_count": config.transaction_count,
                    "aggressive_equals_balanced_rate": "1.000000",
                    "interpretation": "fixture",
                },
            },
            "dynamic": {
                "record_count": config.dynamic_record_count,
                "dataset_seed": config.dynamic_seed,
                "static": dynamic_metrics,
                "dynamic": dynamic_metrics,
                "dynamic_diagnostics": {
                    "average_initial_block_paise": 1_000,
                    "average_final_authorized_block_paise": 1_000,
                    "average_total_additional_block_paise": 0,
                    "average_additional_when_triggered_paise": 0,
                    "rides_requiring_additional_block_rate": "0.000000",
                    "average_reoptimization_count": 1.0,
                    "average_block_increase_count": 0.0,
                },
                "evaluation_scope": "fixture",
                "authorization_assumption": "fixture",
                "benefit_breakdown": {
                    "static_failed_dynamic_succeeded": 0,
                    "static_failed_dynamic_succeeded_rate": "0.000000",
                    "both_succeeded": config.dynamic_record_count,
                    "both_succeeded_rate": "1.000000",
                    "both_failed": 0,
                    "both_failed_rate": "0.000000",
                    "static_succeeded_dynamic_failed": 0,
                    "static_succeeded_dynamic_failed_rate": "0.000000",
                    "dynamic_no_increase_required": 0,
                    "dynamic_no_increase_required_rate": "0.000000",
                },
            },
            "cities": cities,
            "agents": {
                "runs": config.agent_record_count,
                "successful_runs": config.agent_record_count,
                "failed_runs": 0,
                "decision_mismatches": 0,
                "equivalence_rate": "1.000000",
                "decision_equivalence_rate": "1.000000",
                "total_tool_calls": config.agent_record_count * 4,
                "average_tool_calls": 4.0,
                "average_execution_time_ms": 1.0,
                "median_execution_time_ms": 1.0,
                "p95_execution_time_ms": 1.0,
                "step_limit_failures": 0,
            },
            "explainability": {
                "record_count": config.agent_record_count,
                "explanations_generated": config.agent_record_count,
                "structured_valid_count": config.agent_record_count,
                "numeric_consistency_failures": 0,
                "privacy_violations": 0,
                "structured_valid_rate": "1.000000",
                "template_fallbacks": 0,
                "generated_text_failures": 0,
                "renderers": {"deterministic": config.agent_record_count},
            },
            "reserve_pay_mock_validation": {
                "provider": "mock",
                "network_calls_made": False,
                "total_scenarios": 11,
                "passed_scenarios": 11,
                "failed_scenarios": 0,
                "scenarios": [
                    {
                        "scenario": name,
                        "expected_state": "expected",
                        "observed_state": {},
                        "passed": True,
                    }
                    for name in (
                        "create_success", "idempotent_create", "increase_success",
                        "partial_debit", "full_settlement", "release_remaining_amount",
                        "permanent_failure_surfaced", "transient_retry_success",
                        "idempotency_conflict", "stale_success_reconciliation_visible",
                        "under_block_shortfall",
                    )
                ],
            },
            "limitations": ["synthetic"] * 5,
        }
        fingerprint = evidence_fingerprint(artifact)
        artifact["metadata"]["evidence_fingerprint_sha256"] = fingerprint
        artifact["metadata"]["evidence_fingerprint"] = fingerprint
        return artifact

    def test_complete_artifact_contract_accepts_all_required_evidence(self) -> None:
        config = FinalEvidenceConfig()
        validate_final_evidence(self._artifact(config), config)

    def test_evidence_fingerprint_is_stable_but_metric_sensitive(self) -> None:
        artifact = self._artifact(FinalEvidenceConfig())
        first = evidence_fingerprint(artifact)
        artifact["agents"]["average_execution_time_ms"] = 1.0
        artifact["agents"]["median_execution_time_ms"] = 2.0
        artifact["agents"]["p95_execution_time_ms"] = 3.0
        self.assertEqual(evidence_fingerprint(artifact), first)
        changed = deepcopy(artifact)
        changed["primary_strategy_comparison"]["metrics"]["optimized_balanced"]["collection_success_rate"] = "0.800000"
        self.assertNotEqual(evidence_fingerprint(changed), first)

        changed_seed = deepcopy(artifact)
        changed_seed["metadata"]["dataset_seed"] = 99
        changed_seed["metadata"]["dataset_fingerprint_sha256"] = "b" * 64
        changed_seed["metadata"]["dataset_fingerprint"] = "b" * 64
        self.assertNotEqual(evidence_fingerprint(changed_seed), first)

    def test_missing_section_and_non_finite_values_fail_closed(self) -> None:
        config = FinalEvidenceConfig()
        missing = self._artifact(config)
        missing.pop("risk_profiles")
        with self.assertRaises(EvidenceValidationError):
            validate_final_evidence(missing, config)
        invalid = self._artifact(config)
        invalid["agents"]["average_execution_time_ms"] = float("nan")
        with self.assertRaisesRegex(EvidenceValidationError, "non-finite"):
            validate_final_evidence(invalid, config)

    def test_markdown_summary_is_rendered_from_authoritative_fields(self) -> None:
        artifact = self._artifact(FinalEvidenceConfig())
        artifact["metadata"].update({"project_version": "0.14.0", "dataset": "Synthetic", "dataset_seed": 1})
        artifact["primary_strategy_comparison"].setdefault("deltas", {})
        artifact["prediction"].update({"mean_pinball_loss_paise": "1.000000"})
        for key, value in artifact["prediction"]["quantiles"].items():
            value.update({"target_coverage": key, "calibration_error": "0.000000"})
        artifact["risk_profiles"]["profiles"] = {
            key: {"target_collection_probability": "0.970000", "metrics": {"collection_success_rate": "0.900000"}, "average_recommended_block_paise": 100}
            for key in ("aggressive", "balanced", "conservative")
        }
        artifact["risk_profiles"]["collapse_analysis"].update({"all_three_same_rate": "1.000000"})
        artifact["personalization"].update({"test_records": 20000})
        artifact["dynamic"].update({"static": {"collection_success_rate": "0.9"}, "dynamic": {"collection_success_rate": "0.95"}})
        artifact["agents"].update({"successful_runs": 500})
        artifact["explainability"].update({"explanations_generated": 500, "structured_valid_count": 500, "structured_valid_rate": "1.000000", "template_fallbacks": 0, "generated_text_failures": 0})
        text = render_evidence_markdown(artifact)
        self.assertIn("Final PRD Evidence Summary", text)
        self.assertIn("20000", text)

    def test_mock_lifecycle_validation_runs_offline(self) -> None:
        context = generate_dataset(count=1, seed=7, customer_pool_size=1).transactions[0]
        result = validate_mock_reserve_pay(context)
        self.assertFalse(result["network_calls_made"])
        self.assertGreaterEqual(result["total_scenarios"], 11)
        self.assertEqual(result["failed_scenarios"], 0)

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
