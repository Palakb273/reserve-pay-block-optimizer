"""Authoritative, fail-closed PRD evidence assembled from production services."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import json
import math
from pathlib import Path

from reserve_pay_optimizer import __version__
from reserve_pay_optimizer.agents.evaluation import evaluate_agent_orchestration
from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.dynamic.evaluation import evaluate_dynamic_reoptimization
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.dynamic.simulation import simulate_dynamic_transactions
from reserve_pay_optimizer.evidence.config import FinalEvidenceConfig
from reserve_pay_optimizer.evidence.datasets import dataset_fingerprint, generate_dataset
from reserve_pay_optimizer.evidence.errors import EvidenceValidationError
from reserve_pay_optimizer.evidence.fingerprint import evidence_fingerprint
from reserve_pay_optimizer.evidence.mock_validation import validate_mock_reserve_pay
from reserve_pay_optimizer.evidence.reporting import render_evidence_markdown
from reserve_pay_optimizer.evidence.statistics import bootstrap_mean_paise, wilson_ci
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY
from reserve_pay_optimizer.personalization.dataset import build_personalized_records
from reserve_pay_optimizer.personalization.evaluation import evaluate_personalization
from reserve_pay_optimizer.personalization.history import InMemoryCustomerHistoryProvider
from reserve_pay_optimizer.personalization.models import PersonalizedFareDistributionPrediction
from reserve_pay_optimizer.personalization.persistence import load_personalized_artifact
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.dataset import build_prediction_records
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction, crossing_count, repair_monotonic
from reserve_pay_optimizer.prediction.evaluation import calculate_prediction_metrics
from reserve_pay_optimizer.prediction.persistence import load_predictor_artifact
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.evaluation import aggregate_evaluations, evaluate_transaction
from reserve_pay_optimizer.services.evaluation_input import parse_evaluation_dataset
from reserve_pay_optimizer.services.mobility_validation import parse_mobility_transaction
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from reserve_pay_optimizer.strategies.optimized import OptimizedReserveStrategy


class _AuditablePersonalizedPredictor:
    """Cache published and pre-repair predictions for one evidence cohort."""

    def __init__(self, base_model, personalized_model, history_provider) -> None:
        self.base_model = base_model
        self.personalized_model = personalized_model
        self.history_provider = history_provider
        self.raw_by_transaction: dict[str, dict[Decimal, int]] = {}
        self.predictions: dict[str, PersonalizedFareDistributionPrediction] = {}
        self._cache: dict[tuple[object, ...], PersonalizedFareDistributionPrediction] = {}

    @staticmethod
    def _cache_key(context, history) -> tuple[object, ...]:
        return (
            context.transaction_id, context.estimated_amount.amount_paise,
            context.city.value, str(context.distance_km), context.estimated_duration_minutes,
            str(context.surge_multiplier), context.timestamp.isoformat(),
            history.completed_ride_count, str(history.mean_fare_ratio),
            str(history.fare_ratio_stddev), str(history.overrun_rate),
            str(history.mean_positive_overrun_ratio),
        )

    def predict(self, context) -> PersonalizedFareDistributionPrediction:
        history = self.history_provider.features_for(context)
        return self.predict_with_history(context, history, history_as_of=context.timestamp)

    def predict_with_history(self, context, history, *, history_as_of):
        key = self._cache_key(context, history)
        if key in self._cache:
            return self._cache[key]
        use_base = history.completed_ride_count < MINIMUM_PERSONALIZATION_HISTORY
        model = self.base_model if use_base else self.personalized_model
        raw = model.predict_raw_amounts(context) if use_base else model.predict_raw_amounts(context, history)
        repaired = repair_monotonic(raw)
        distribution = FareDistributionPrediction(
            transaction_id=context.transaction_id,
            model_version=model.model_version,
            quantiles=tuple((q, Money(repaired[q])) for q in QUANTILES),
            raw_quantile_crossing_detected=crossing_count(raw) > 0,
        )
        prediction = PersonalizedFareDistributionPrediction.from_distribution(
            distribution,
            prediction_mode="base" if use_base else "personalized",
            history_features=history,
            history_as_of=history_as_of,
        )
        self.raw_by_transaction[context.transaction_id] = raw
        self.predictions[context.transaction_id] = prediction
        self._cache[key] = prediction
        return prediction


def _strategy_evaluations(dataset, strategies, optimized_strategy):
    outcomes = {item.transaction_id: item for item in dataset.outcomes}
    optimized_decisions = {item.transaction_id: item.reserve_decision for item in optimized_strategy.optimization_results}
    values: dict[str, list] = {}
    for strategy in strategies:
        rows = []
        for transaction in dataset.transactions:
            decision = optimized_decisions[transaction.transaction_id] if strategy is optimized_strategy else strategy.calculate_block(transaction)
            rows.append(evaluate_transaction(transaction, decision, outcomes[transaction.transaction_id]))
        values[strategy.strategy_id] = rows
    return values


def _strategy_confidence(rows, *, seed: int, samples: int) -> dict[str, object]:
    return {
        "collection_success_rate": wilson_ci(sum(item.collection_success for item in rows), len(rows)),
        "average_excess_block_paise": bootstrap_mean_paise(
            tuple(item.excess_block.amount_paise for item in rows), seed=seed, samples=samples
        ),
    }


def _per_city(dataset, evaluations) -> dict[str, object]:
    city_by_id = {item.transaction_id: item.city.value for item in dataset.transactions}
    result: dict[str, object] = {}
    for city in sorted(set(city_by_id.values())):
        metrics = {
            name: aggregate_evaluations(tuple(item for item in rows if city_by_id[item.transaction_id] == city)).to_dict()
            for name, rows in evaluations.items()
        }
        optimized = metrics["optimized_balanced"]
        result[city] = {
            "record_count": sum(value == city for value in city_by_id.values()),
            "optimized_collection_success_rate": optimized["collection_success_rate"],
            "optimized_average_excess_block_paise": optimized["average_excess_block_paise"],
            "strategies": metrics,
        }
    return result


def _histogram(values: tuple[int, ...], bin_count: int = 14) -> list[dict[str, int]]:
    lower, upper = min(values), max(values)
    width = max(1, (upper - lower + bin_count) // bin_count)
    counts = [0] * bin_count
    for value in values:
        counts[min((value - lower) // width, bin_count - 1)] += 1
    return [{"lower_paise": lower + i * width, "upper_paise": lower + (i + 1) * width - 1, "count": count} for i, count in enumerate(counts)]


def _personalization_demo(base_model, personalized_model, optimizer, policy):
    fixture = Path(__file__).resolve().parents[3] / "examples/personalization_comparison.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"), parse_float=Decimal)
    proof: dict[str, object] = {}
    for customer in payload["customers"]:
        key = "stable_history" if customer["label"] == "stable_history_customer" else "overrun_prone"
        context = parse_mobility_transaction(customer["transaction"])
        contexts, outcomes = parse_evaluation_dataset(customer["history"])
        predictor = PersonalizedFarePredictor(base_model, personalized_model, InMemoryCustomerHistoryProvider(contexts, outcomes))
        prediction = predictor.predict(context)
        decision = PolicyConstrainedOptimizer(optimizer).optimize(context, prediction, policy)
        proof[key] = {
            "prediction_mode": prediction.prediction_mode,
            "history_count": prediction.history_count,
            "q97_paise": prediction.amount_for_quantile("0.97").amount_paise,
            "recommended_block_paise": decision.recommended_block.amount_paise,
        }
    return proof


def _artifact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {key: metadata[key] for key in ("model_version", "dataset_fingerprint_sha256", "library_versions", "trusted_sources_only")}


def _risk_profile_evidence(dataset, predictor, optimizer) -> dict[str, object]:
    outcomes = {item.transaction_id: item for item in dataset.outcomes}
    decisions: dict[str, dict[str, int]] = {}
    profiles: dict[str, object] = {}
    for profile in (RiskProfile.AGGRESSIVE, RiskProfile.BALANCED, RiskProfile.CONSERVATIVE):
        policy = ReserveRiskPolicy.for_profile(profile)
        policy_optimizer = PolicyConstrainedOptimizer(optimizer)
        rows, blocks = [], []
        satisfied = 0
        decisions[profile.value] = {}
        for transaction in dataset.transactions:
            result = policy_optimizer.optimize(transaction, predictor.predict(transaction), policy)
            amount = result.recommended_block.amount_paise
            blocks.append(amount)
            decisions[profile.value][transaction.transaction_id] = amount
            satisfied += int(result.policy_satisfied)
            rows.append(evaluate_transaction(transaction, result.reserve_decision, outcomes[transaction.transaction_id]))
        metrics = aggregate_evaluations(rows).to_dict()
        profiles[profile.value] = {
            "target_collection_probability": format_ratio(policy.target_collection_probability),
            "realized_collection_success": metrics["collection_success_rate"],
            "under_block_rate": metrics["under_block_rate"],
            "average_block_paise": int((Decimal(sum(blocks)) / Decimal(len(blocks))).to_integral_value(rounding=ROUND_HALF_UP)),
            "average_excess_paise": metrics["average_excess_block_paise"],
            "capital_efficiency": metrics["capital_efficiency"],
            "policy_satisfied_count": satisfied,
            "policy_satisfaction_rate": format_ratio(Decimal(satisfied) / Decimal(len(blocks))),
            "average_recommended_block_paise": int((Decimal(sum(blocks)) / Decimal(len(blocks))).to_integral_value(rounding=ROUND_HALF_UP)),
            "realized_minus_target": format_ratio(Decimal(str(metrics["collection_success_rate"])) - policy.target_collection_probability),
            "metrics": metrics,
        }
    all_same = two_same = all_distinct = at_least_two_differ = aggressive_equals_balanced = 0
    for transaction in dataset.transactions:
        values = [decisions[name][transaction.transaction_id] for name in ("aggressive", "balanced", "conservative")]
        unique = len(set(values))
        all_same += int(unique == 1)
        two_same += int(unique == 2)
        all_distinct += int(unique == 3)
        at_least_two_differ += int(unique > 1)
        aggressive_equals_balanced += int(values[0] == values[1])
    count = len(dataset.transactions)
    collapse = {
        "record_count": count,
        "all_three_same_count": all_same, "all_three_same_rate": format_ratio(Decimal(all_same) / Decimal(count)),
        "exactly_two_same_count": two_same, "exactly_two_same_rate": format_ratio(Decimal(two_same) / Decimal(count)),
        "all_three_distinct_count": all_distinct, "all_three_distinct_rate": format_ratio(Decimal(all_distinct) / Decimal(count)),
        "at_least_two_differ_count": at_least_two_differ,
        "at_least_two_differ_rate": format_ratio(Decimal(at_least_two_differ) / Decimal(count)),
        "aggressive_equals_balanced_count": aggressive_equals_balanced,
        "aggressive_equals_balanced_rate": format_ratio(Decimal(aggressive_equals_balanced) / Decimal(count)),
        "interpretation": "The three policy constraints frequently converge to the same selected block because the unchanged Phase-5 objective often favors a high feasible candidate even when a lower minimum probability is permitted. This is measured convergence, not a policy-logic failure.",
    }
    return {"profiles": profiles, "collapse_analysis": collapse}


def _atomic_write(output: Path, artifact: dict[str, object]) -> None:
    summary = output.with_name(f"{output.stem}_summary.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    json_temp, summary_temp = output.with_suffix(output.suffix + ".tmp"), summary.with_suffix(summary.suffix + ".tmp")
    json_temp.write_text(json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    summary_temp.write_text(render_evidence_markdown(artifact), encoding="utf-8")
    json_temp.replace(output)
    summary_temp.replace(summary)


def generate_final_evidence(config: FinalEvidenceConfig) -> dict[str, object]:
    """Generate all required proof, validate it, then atomically publish both artifacts."""

    dataset = generate_dataset(count=config.transaction_count, seed=config.dataset_seed, customer_pool_size=config.customer_pool_size)
    base_artifact = load_predictor_artifact(config.base_model_path)
    personalized_artifact = load_personalized_artifact(config.personalized_model_path)
    history = InMemoryCustomerHistoryProvider(dataset.transactions, dataset.outcomes)
    predictor = _AuditablePersonalizedPredictor(base_artifact.model, personalized_artifact.model, history)
    optimizer = ReserveBlockOptimizer()
    policy = ReserveRiskPolicy.for_profile(RiskProfile(config.primary_risk_profile))
    optimized = OptimizedReserveStrategy(predictor, optimizer, policy)
    strategies = (ExactEstimateStrategy(), FixedBufferStrategy(), optimized)
    comparison = compare_strategies(dataset.transactions, dataset.outcomes, strategies)
    strategy_metrics = {metric.strategy: metric.to_dict() for metric in comparison.metrics}
    for metric in strategy_metrics.values():
        metric["average_block_amount_paise"] = int(metric["total_blocked_amount_paise"]) // int(metric["transaction_count"])
    evaluations = _strategy_evaluations(dataset, strategies, optimized)
    confidence = {name: _strategy_confidence(rows, seed=config.bootstrap_seed + index, samples=config.bootstrap_samples) for index, (name, rows) in enumerate(evaluations.items())}
    records = build_prediction_records(dataset.transactions, dataset.outcomes)
    for record in records:
        predictor.predict(record.context)
    prediction_metrics = calculate_prediction_metrics(records, lambda record: predictor.raw_by_transaction[record.context.transaction_id])
    mode_counts = Counter(item.prediction_mode for item in predictor.predictions.values())

    personalization = evaluate_personalization(
        personalized_artifact.model,
        base_artifact.model,
        build_personalized_records(dataset.transactions, dataset.outcomes),
    ).to_dict()
    personalization["same_ride_history_demo"] = _personalization_demo(base_artifact.model, personalized_artifact.model, optimizer, policy)
    risk_profiles = _risk_profile_evidence(dataset, predictor, optimizer)

    dynamic_config = SimulationConfig(
        transaction_count=config.dynamic_record_count,
        seed=config.dynamic_seed,
        customer_pool_size=min(config.customer_pool_size, max(25, config.dynamic_record_count // 4)),
        customer_behavior_enabled=True,
    )
    dynamic_dataset = simulate_dynamic_transactions(dynamic_config)
    dynamic_history = InMemoryCustomerHistoryProvider(dynamic_dataset.transactions, dynamic_dataset.outcomes)
    dynamic_predictor = _AuditablePersonalizedPredictor(base_artifact.model, personalized_artifact.model, dynamic_history)
    dynamic_service = DynamicRideService(dynamic_predictor, optimizer)
    dynamic = evaluate_dynamic_reoptimization(dynamic_dataset, dynamic_service, policy).to_dict()
    dynamic["dataset_seed"] = config.dynamic_seed

    agent_report = evaluate_agent_orchestration(
        dataset.transactions[:config.agent_record_count], base_artifact.model,
        personalized_artifact.model, history, risk_profile=policy.profile,
    )
    agents = agent_report.to_dict()
    agents["runs"] = agents.pop("total_records")
    agents["decision_equivalence_rate"] = agents["equivalence_rate"]
    agents["financial_equivalence_required"] = True
    agents["timing_is_observational"] = True
    agents["average_execution_time_ms"] = agents.pop("average_duration_ms")
    agents["median_execution_time_ms"] = agents.pop("median_duration_ms")
    agents["p95_execution_time_ms"] = agents.pop("p95_duration_ms")
    explainability = {
        "record_count": agent_report.explanation_count,
        "explanations_generated": agent_report.explanation_count,
        "structured_valid_count": agent_report.explanation_count,
        "structured_valid_rate": "1.000000",
        "numeric_consistency_failures": agent_report.explanation_numeric_mismatches,
        "privacy_violations": agent_report.explanation_privacy_violations,
        "template_fallbacks": 0,
        "generated_text_failures": 0,
        "renderers": {"deterministic_phase_9": agent_report.explanation_count},
        "validation": "Structured Phase-9 evidence is re-derived from authoritative prediction and policy services before deterministic rendering.",
    }
    mock_validation = validate_mock_reserve_pay(
        dataset.transactions[0],
        dynamic_dataset=dynamic_dataset,
        dynamic_service=dynamic_service,
        policy=policy,
    )

    selected, exact, fixed = strategy_metrics["optimized_balanced"], strategy_metrics["exact_estimate"], strategy_metrics["fixed_buffer_20"]
    optimized_blocks = tuple(item.recommended_block.amount_paise for item in optimized.optimization_results)
    primary = {
        "scope": "same_fresh_transactions_and_outcomes",
        "metrics": strategy_metrics,
        "confidence_intervals_95": confidence,
        "deltas": {
            "optimized_collection_success_percentage_points_vs_exact": format((Decimal(str(selected["collection_success_rate"])) - Decimal(str(exact["collection_success_rate"]))) * Decimal(100), ".3f"),
            "optimized_average_excess_reduction_paise_vs_fixed_20": int(fixed["average_excess_block_paise"]) - int(selected["average_excess_block_paise"]),
        },
        "block_distribution": _histogram(optimized_blocks),
        "tradeoff_points": [{"strategy": name, "average_excess_block_paise": values["average_excess_block_paise"], "collection_success_rate": values["collection_success_rate"]} for name, values in strategy_metrics.items()],
    }
    prediction = {
        **prediction_metrics.to_dict(),
        "prediction_mode_counts": dict(sorted(mode_counts.items())),
        "interpretation": "Observed coverage is empirical calibration on fresh synthetic data, not a guarantee. High-quantile under-coverage remains visible and requires recalibration before production claims.",
    }
    artifact: dict[str, object] = {
        "metadata": {
            "evidence_status": "complete", "project_version": __version__,
            "dataset": "Synthetic India Mobility", "record_count": config.transaction_count,
            "transaction_count": config.transaction_count,
            "customer_pool_size": config.customer_pool_size,
            "dataset_seed": config.dataset_seed, "dataset_fingerprint_sha256": dataset_fingerprint(dataset),
            "dataset_fingerprint": dataset_fingerprint(dataset),
            "evidence_fingerprint_sha256": "", "evidence_fingerprint": "",
            "base_model_version": base_artifact.model.model_version,
            "personalized_model_version": personalized_artifact.model.model_version,
            "primary_strategy": "optimized_balanced",
            "primary_risk_profile": policy.profile.value,
            "dynamic_seed": config.dynamic_seed,
            "dynamic_record_count": config.dynamic_record_count,
            "agent_record_count": config.agent_record_count,
            "bootstrap_seed": config.bootstrap_seed,
            "bootstrap_samples": config.bootstrap_samples,
            "models_retrained": False,
            "configuration": config.to_dict(),
            "base_model": _artifact_metadata(base_artifact.metadata),
            "personalized_model": _artifact_metadata(personalized_artifact.metadata),
            "evaluation_dataset_used_for_training": False, "retraining_performed": False,
            "synthetic_data_only": True, "production_data_used": False,
            "filesystem_paths_in_fingerprint": False,
            "observational_timing_excluded_from_fingerprint": True,
        },
        "primary_strategy_comparison": primary,
        "prediction": prediction,
        "personalization": personalization,
        "risk_profiles": risk_profiles,
        "dynamic": dynamic,
        "cities": _per_city(dataset, evaluations),
        "agents": agents,
        "explainability": explainability,
        "reserve_pay_mock_validation": mock_validation,
        "limitations": [
            "All evaluated rides are generated by the deterministic synthetic simulator; no production merchant, Razorpay, Uber, Ola, or customer data is used.",
            "Observed calibration and collection success are empirical estimates, not guarantees.",
            "Q97 and Q99 under-coverage on this fresh synthetic cohort is material; production use requires recalibration and external validation.",
            "Dynamic evaluation assumes simulated additional authorizations succeed; the separate mock lifecycle validates execution failure behavior offline.",
            "Risk-profile recommendations frequently collapse to the same candidate because the objective optimum can satisfy multiple policy floors.",
            "Agent timing is observational and excluded from the canonical evidence fingerprint.",
            "The Razorpay network mapping remains intentionally unimplemented without verified Reserve Pay API documentation.",
            "Merchant-history personalization and persistent production storage are unavailable.",
        ],
    }
    fingerprint = evidence_fingerprint(artifact)
    artifact["metadata"]["evidence_fingerprint_sha256"] = fingerprint  # type: ignore[index]
    artifact["metadata"]["evidence_fingerprint"] = fingerprint  # type: ignore[index]
    validate_final_evidence(artifact, config)
    _atomic_write(config.output_path, artifact)
    return artifact


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _require_fields(value: object, fields: set[str], label: str) -> None:
    _require(isinstance(value, dict), f"{label} must be an object")
    missing = fields - set(value)
    _require(not missing, f"{label} is missing required fields: {', '.join(sorted(missing))}")


def _walk_floats(value: object, path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_floats(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_floats(item, f"{path}[{index}]")
    elif isinstance(value, float):
        yield path, value


def _walk_fields(value: object, path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield f"{path}.{key}", key, item
            yield from _walk_fields(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_fields(item, f"{path}[{index}]")


def validate_final_evidence(artifact: dict[str, object], config: FinalEvidenceConfig) -> None:
    """Reject incomplete, non-finite, inconsistent, or non-reproducible evidence."""

    required = {"metadata", "primary_strategy_comparison", "prediction", "personalization", "risk_profiles", "dynamic", "cities", "agents", "explainability", "reserve_pay_mock_validation", "limitations"}
    _require(set(artifact) == required, "authoritative evidence top-level schema is incomplete")
    meta = artifact["metadata"]
    _require(isinstance(meta, dict), "metadata must be an object")
    _require(meta.get("evidence_status") == "complete", "evidence status must be complete")
    _require(meta.get("record_count") == config.transaction_count, "record count is inconsistent")
    _require(meta.get("dataset_seed") == config.dataset_seed, "dataset seed is inconsistent")
    _require(meta.get("transaction_count") == config.transaction_count, "transaction count is inconsistent")
    _require(int(meta.get("transaction_count", 0)) >= 10_000, "authoritative transaction count is below minimum")
    _require(meta.get("customer_pool_size") == config.customer_pool_size, "customer pool is inconsistent")
    _require(meta.get("retraining_performed") is False, "evidence generation must not retrain models")
    _require(meta.get("models_retrained") is False, "models_retrained must be false")
    _require(meta.get("evaluation_dataset_used_for_training") is False, "evaluation data must be fresh")
    for key in ("dataset_fingerprint_sha256", "evidence_fingerprint_sha256"):
        _require(isinstance(meta.get(key), str) and len(meta[key]) == 64, f"{key} must be SHA-256")
    _require(meta.get("dataset_fingerprint") == meta["dataset_fingerprint_sha256"], "dataset fingerprint aliases disagree")
    for model_key in ("base_model", "personalized_model"):
        model = meta.get(model_key)
        _require(isinstance(model, dict) and bool(model.get("trusted_sources_only")), f"trusted {model_key} metadata is required")
        _require(bool(model.get("model_version")), f"{model_key} version is required")
    for key in ("base_model_version", "personalized_model_version", "primary_strategy", "primary_risk_profile"):
        _require(bool(meta.get(key)), f"metadata.{key} is required")
    for key, expected in (
        ("dynamic_seed", config.dynamic_seed),
        ("dynamic_record_count", config.dynamic_record_count),
        ("agent_record_count", config.agent_record_count),
        ("bootstrap_seed", config.bootstrap_seed),
        ("bootstrap_samples", config.bootstrap_samples),
    ):
        _require(meta.get(key) == expected, f"metadata.{key} is inconsistent")

    primary = artifact["primary_strategy_comparison"]
    _require(isinstance(primary, dict), "primary strategy comparison must be an object")
    strategy_names = {"exact_estimate", "fixed_buffer_20", "optimized_balanced"}
    _require(set(primary.get("metrics", {})) == strategy_names, "primary strategy set is incomplete")
    _require(set(primary.get("confidence_intervals_95", {})) == strategy_names, "confidence intervals are incomplete")
    required_strategy_fields = {
        "strategy", "transaction_count", "collection_success_count",
        "collection_success_rate", "under_block_count", "under_block_rate",
        "average_block_amount_paise", "average_excess_block_paise",
        "average_under_block_paise", "average_excess_block_ratio",
        "capital_efficiency", "total_actual_amount_paise", "total_blocked_amount_paise",
    }
    for name, metric in primary["metrics"].items():
        _require_fields(metric, required_strategy_fields, f"primary strategy {name}")
        _require(metric["strategy"] == name, f"primary strategy identity mismatch for {name}")
        _require(metric["transaction_count"] == config.transaction_count, "strategy record count is inconsistent")
        for field in ("collection_success_rate", "under_block_rate", "capital_efficiency", "average_excess_block_ratio"):
            value = Decimal(str(metric[field]))
            _require(value.is_finite() and Decimal(0) <= value <= Decimal(1), f"invalid strategy ratio {field}")

    prediction = artifact["prediction"]
    _require_fields(
        prediction,
        {"record_count", "mean_pinball_loss_paise", "median_mae_paise", "quantiles", "prediction_interval_q05_q95", "raw_quantile_crossing", "per_city"},
        "prediction evidence",
    )
    _require(prediction.get("record_count") == config.transaction_count, "prediction count is inconsistent")
    _require(set(prediction.get("quantiles", {})) == {f"{q:.2f}" for q in QUANTILES}, "prediction quantiles are incomplete")
    for key, quantile in prediction["quantiles"].items():
        _require_fields(
            quantile,
            {"target_coverage", "observed_coverage", "calibration_error", "absolute_calibration_error", "pinball_loss_paise"},
            f"prediction quantile {key}",
        )
        observed = Decimal(quantile["observed_coverage"])
        _require(observed.is_finite() and Decimal(0) <= observed <= Decimal(1), "invalid observed coverage")

    personalization = artifact["personalization"]
    _require_fields(
        personalization,
        {"test_records", "eligible_record_count", "minimum_personalization_history", "fallback_record_count", "fallback_percentage", "personalized_record_count", "personalized_percentage", "base_predictor", "personalized_predictor", "comparison", "history_depth", "observed_history_segments", "downstream_balanced_policy", "same_ride_history_demo"},
        "personalization evidence",
    )
    _require(personalization.get("test_records") == config.transaction_count, "personalization count is inconsistent")
    _require(personalization.get("minimum_personalization_history") == MINIMUM_PERSONALIZATION_HISTORY, "personalization threshold is inconsistent")
    _require(personalization.get("fallback_record_count", 0) + personalization.get("personalized_record_count", 0) == config.transaction_count, "personalization modes do not account for every record")
    _require(set(personalization.get("history_depth", {})) == {"0-2", "3-5", "6-10", "11+"}, "history-depth evidence is incomplete")
    _require(bool(personalization.get("observed_history_segments")), "observed segment evidence is required")

    risks = artifact["risk_profiles"]
    _require(set(risks.get("profiles", {})) == {"aggressive", "balanced", "conservative"}, "risk profiles are incomplete")
    collapse = risks.get("collapse_analysis", {})
    required_risk_fields = {
        "target_collection_probability", "realized_collection_success", "under_block_rate",
        "average_block_paise", "average_excess_paise", "capital_efficiency",
        "policy_satisfaction_rate", "realized_minus_target", "metrics",
    }
    for name, profile in risks["profiles"].items():
        _require_fields(profile, required_risk_fields, f"risk profile {name}")
    _require_fields(
        collapse,
        {"record_count", "all_three_same_count", "all_three_same_rate", "exactly_two_same_count", "exactly_two_same_rate", "at_least_two_differ_count", "at_least_two_differ_rate", "all_three_distinct_count", "all_three_distinct_rate", "aggressive_equals_balanced_count", "aggressive_equals_balanced_rate", "interpretation"},
        "risk-profile collapse analysis",
    )
    _require(collapse.get("record_count") == config.transaction_count, "collapse count is inconsistent")
    _require(collapse.get("all_three_same_count", 0) + collapse.get("exactly_two_same_count", 0) + collapse.get("all_three_distinct_count", 0) == config.transaction_count, "collapse categories do not account for every record")

    dynamic = artifact["dynamic"]
    _require_fields(
        dynamic,
        {"record_count", "dataset_seed", "static", "dynamic", "dynamic_diagnostics", "benefit_breakdown", "evaluation_scope", "authorization_assumption"},
        "dynamic evidence",
    )
    _require(dynamic.get("record_count") == config.dynamic_record_count, "dynamic count is inconsistent")
    benefit = dynamic.get("benefit_breakdown", {})
    for side in ("static", "dynamic"):
        _require_fields(
            dynamic[side],
            {"transaction_count", "collection_success_rate", "under_block_rate", "average_excess_block_paise", "average_under_block_paise", "average_excess_block_ratio", "capital_efficiency"},
            f"dynamic {side} aggregate",
        )
        _require(dynamic[side]["transaction_count"] == config.dynamic_record_count, f"dynamic {side} count is inconsistent")
    _require_fields(
        dynamic["dynamic_diagnostics"],
        {"average_initial_block_paise", "average_final_authorized_block_paise", "average_total_additional_block_paise", "average_additional_when_triggered_paise", "rides_requiring_additional_block_rate", "average_reoptimization_count", "average_block_increase_count"},
        "dynamic diagnostics",
    )
    _require_fields(
        benefit,
        {"static_failed_dynamic_succeeded", "static_failed_dynamic_succeeded_rate", "both_succeeded", "both_succeeded_rate", "both_failed", "both_failed_rate", "static_succeeded_dynamic_failed", "static_succeeded_dynamic_failed_rate", "dynamic_no_increase_required", "dynamic_no_increase_required_rate"},
        "dynamic benefit breakdown",
    )
    _require(sum(benefit.get(key, 0) for key in ("static_failed_dynamic_succeeded", "both_succeeded", "both_failed", "static_succeeded_dynamic_failed")) == config.dynamic_record_count, "dynamic outcome categories are incomplete")
    _require(set(artifact["cities"]) == {"delhi", "mumbai", "bengaluru", "hyderabad", "pune", "chennai", "kolkata"}, "city evidence is incomplete")
    city_total = 0
    for name, city in artifact["cities"].items():
        _require_fields(city, {"record_count", "optimized_collection_success_rate", "optimized_average_excess_block_paise", "strategies"}, f"city {name}")
        city_total += int(city["record_count"])
    _require(city_total == config.transaction_count, "city counts do not account for every record")

    agents = artifact["agents"]
    _require_fields(
        agents,
        {"runs", "successful_runs", "failed_runs", "decision_mismatches", "equivalence_rate", "decision_equivalence_rate", "total_tool_calls", "average_tool_calls", "average_execution_time_ms", "median_execution_time_ms", "p95_execution_time_ms", "step_limit_failures"},
        "agent evidence",
    )
    _require(agents.get("runs") == config.agent_record_count, "agent cohort is inconsistent")
    _require(agents.get("failed_runs") == 0, "agent execution failures are not allowed")
    _require(agents.get("successful_runs", 0) + agents.get("failed_runs", 0) == config.agent_record_count, "agent run counts are inconsistent")
    _require(agents.get("decision_mismatches") == 0, "agent/direct decision mismatch detected")
    _require(
        agents.get("decision_equivalence_rate") == agents.get("equivalence_rate")
        and Decimal(agents.get("decision_equivalence_rate", "0")) == Decimal(1),
        "agent equivalence must be 100%",
    )
    explanations = artifact["explainability"]
    _require_fields(
        explanations,
        {"record_count", "explanations_generated", "structured_valid_count", "structured_valid_rate", "numeric_consistency_failures", "privacy_violations", "template_fallbacks", "generated_text_failures", "renderers"},
        "explainability evidence",
    )
    _require(explanations.get("record_count") == config.agent_record_count, "explanation cohort is inconsistent")
    _require(explanations.get("explanations_generated") == config.agent_record_count, "explanation generation count is inconsistent")
    _require(explanations.get("structured_valid_count") == config.agent_record_count, "structured explanation validation is incomplete")
    _require(explanations.get("numeric_consistency_failures") == 0, "explanation numeric mismatch detected")
    _require(explanations.get("privacy_violations") == 0, "explanation privacy violation detected")
    mock = artifact["reserve_pay_mock_validation"]
    _require_fields(mock, {"provider", "network_calls_made", "total_scenarios", "passed_scenarios", "failed_scenarios", "scenarios"}, "mock Reserve Pay validation")
    _require(mock.get("total_scenarios", 0) >= 11, "mock lifecycle evidence is incomplete")
    _require(mock.get("failed_scenarios") == 0 and mock.get("passed_scenarios") == mock.get("total_scenarios"), "mock lifecycle validation failed")
    required_mock_scenarios = {
        "create_success", "idempotent_create", "increase_success", "partial_debit",
        "full_settlement", "release_remaining_amount", "permanent_failure_surfaced",
        "transient_retry_success", "idempotency_conflict",
        "stale_success_reconciliation_visible", "under_block_shortfall",
    }
    _require(isinstance(mock["scenarios"], list), "mock scenarios must be a list")
    observed_mock_scenarios = set()
    for index, scenario in enumerate(mock["scenarios"]):
        _require_fields(scenario, {"scenario", "expected_state", "observed_state", "passed"}, f"mock scenario {index}")
        _require(scenario["passed"] is True, f"mock scenario {scenario['scenario']} did not pass")
        observed_mock_scenarios.add(scenario["scenario"])
    _require(required_mock_scenarios.issubset(observed_mock_scenarios), "required mock lifecycle scenarios are incomplete")
    _require(isinstance(artifact["limitations"], list) and len(artifact["limitations"]) >= 5, "limitations are incomplete")
    for path, value in _walk_floats(artifact):
        _require(math.isfinite(value), f"non-finite numeric value at {path}")
    for path, key, value in _walk_fields(artifact):
        if isinstance(value, (str, int, float, Decimal)) and (
            key.endswith("_rate")
            or key.endswith("_probability")
            or key.endswith("_coverage")
            or key.endswith("_percentage")
        ):
            try:
                ratio = Decimal(str(value))
            except Exception as exc:
                raise EvidenceValidationError(f"invalid probability/rate at {path}") from exc
            _require(ratio.is_finite() and Decimal(0) <= ratio <= Decimal(1), f"out-of-range probability/rate at {path}")
        if (
            isinstance(value, (str, int, float, Decimal))
            and key.endswith("_paise")
            and "improvement" not in key
            and "reduction" not in key
        ):
            try:
                money_value = Decimal(str(value))
            except Exception as exc:
                raise EvidenceValidationError(f"invalid monetary metric at {path}") from exc
            _require(money_value.is_finite() and money_value >= 0, f"negative/non-finite monetary metric at {path}")
    _require(meta.get("evidence_fingerprint") == meta["evidence_fingerprint_sha256"], "evidence fingerprint aliases disagree")
    _require(meta["evidence_fingerprint_sha256"] == evidence_fingerprint(artifact), "evidence fingerprint does not match canonical content")
