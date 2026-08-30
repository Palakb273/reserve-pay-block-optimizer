"""Authoritative Phase-13 evaluation assembled from existing project services."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
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
from reserve_pay_optimizer.evidence.statistics import bootstrap_mean_paise, wilson_ci
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY
from reserve_pay_optimizer.personalization.history import InMemoryCustomerHistoryProvider
from reserve_pay_optimizer.personalization.models import PersonalizedFareDistributionPrediction
from reserve_pay_optimizer.personalization.persistence import load_personalized_artifact
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.dataset import build_prediction_records
from reserve_pay_optimizer.prediction.distribution import (
    FareDistributionPrediction,
    crossing_count,
    repair_monotonic,
)
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
            context.transaction_id,
            context.estimated_amount.amount_paise,
            context.city.value,
            str(context.distance_km),
            context.estimated_duration_minutes,
            str(context.surge_multiplier),
            context.timestamp.isoformat(),
            history.completed_ride_count,
            str(history.mean_fare_ratio),
            str(history.fare_ratio_stddev),
            str(history.overrun_rate),
            str(history.mean_positive_overrun_ratio),
        )

    def predict(self, context) -> PersonalizedFareDistributionPrediction:
        history = self.history_provider.features_for(context)
        return self.predict_with_history(
            context,
            history,
            history_as_of=context.timestamp,
        )

    def predict_with_history(
        self,
        context,
        history,
        *,
        history_as_of,
    ) -> PersonalizedFareDistributionPrediction:
        key = self._cache_key(context, history)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if history.completed_ride_count < MINIMUM_PERSONALIZATION_HISTORY:
            mode = "base"
            model = self.base_model
            raw = model.predict_raw_amounts(context)
        else:
            mode = "personalized"
            model = self.personalized_model
            raw = model.predict_raw_amounts(context, history)
        repaired = repair_monotonic(raw)
        distribution = FareDistributionPrediction(
            transaction_id=context.transaction_id,
            model_version=model.model_version,
            quantiles=tuple(
                (quantile, Money(repaired[quantile])) for quantile in QUANTILES
            ),
            raw_quantile_crossing_detected=crossing_count(raw) > 0,
        )
        prediction = PersonalizedFareDistributionPrediction.from_distribution(
            distribution,
            prediction_mode=mode,
            history_features=history,
            history_as_of=history_as_of,
        )
        self.raw_by_transaction[context.transaction_id] = raw
        self.predictions[context.transaction_id] = prediction
        self._cache[key] = prediction
        return prediction


def _strategy_evaluations(dataset, strategies, optimized_strategy):
    outcomes = {item.transaction_id: item for item in dataset.outcomes}
    optimized_decisions = {
        item.transaction_id: item.reserve_decision
        for item in optimized_strategy.optimization_results
    }
    values: dict[str, list] = {}
    for strategy in strategies:
        evaluations = []
        for transaction in dataset.transactions:
            decision = (
                optimized_decisions[transaction.transaction_id]
                if strategy is optimized_strategy
                else strategy.calculate_block(transaction)
            )
            evaluations.append(
                evaluate_transaction(
                    transaction,
                    decision,
                    outcomes[transaction.transaction_id],
                )
            )
        values[strategy.strategy_id] = evaluations
    return values


def _strategy_confidence(evaluations, *, seed: int, samples: int) -> dict[str, object]:
    return {
        "collection_success_rate": wilson_ci(
            sum(item.collection_success for item in evaluations), len(evaluations)
        ),
        "average_excess_block_paise": bootstrap_mean_paise(
            tuple(item.excess_block.amount_paise for item in evaluations),
            seed=seed,
            samples=samples,
        ),
    }


def _per_city(dataset, evaluations_by_strategy) -> dict[str, object]:
    city_by_transaction = {
        transaction.transaction_id: transaction.city.value
        for transaction in dataset.transactions
    }
    cities: dict[str, dict[str, object]] = {}
    for city in sorted(set(city_by_transaction.values())):
        strategy_metrics = {}
        for strategy, evaluations in evaluations_by_strategy.items():
            selected = [
                item
                for item in evaluations
                if city_by_transaction[item.transaction_id] == city
            ]
            strategy_metrics[strategy] = aggregate_evaluations(selected).to_dict()
        optimized_key = next(
            key for key in strategy_metrics if key.startswith("optimized_")
        )
        optimized = strategy_metrics[optimized_key]
        cities[city] = {
            "record_count": sum(value == city for value in city_by_transaction.values()),
            "optimized_collection_success_rate": optimized["collection_success_rate"],
            "optimized_average_excess_block_paise": optimized["average_excess_block_paise"],
            "strategies": strategy_metrics,
        }
    return cities


def _histogram(values: tuple[int, ...], bin_count: int = 14) -> list[dict[str, int]]:
    lower = min(values)
    upper = max(values)
    width = max(1, (upper - lower + bin_count) // bin_count)
    counts = [0] * bin_count
    for value in values:
        counts[min((value - lower) // width, bin_count - 1)] += 1
    return [
        {
            "lower_paise": lower + index * width,
            "upper_paise": lower + (index + 1) * width - 1,
            "count": count,
        }
        for index, count in enumerate(counts)
    ]


def _personalization_proof(
    base_model, personalized_model, optimizer, policy
) -> dict[str, object]:
    fixture = Path(__file__).resolve().parents[3] / "examples/personalization_comparison.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"), parse_float=Decimal)
    proof: dict[str, object] = {}
    for customer in payload["customers"]:
        label = customer["label"]
        profile = "stable_history" if label == "stable_history_customer" else "overrun_prone"
        context = parse_mobility_transaction(customer["transaction"])
        contexts, outcomes = parse_evaluation_dataset(customer["history"])
        predictor = PersonalizedFarePredictor(
            base_model,
            personalized_model,
            InMemoryCustomerHistoryProvider(contexts, outcomes),
        )
        prediction = predictor.predict(context)
        decision = PolicyConstrainedOptimizer(optimizer).optimize(
            context,
            prediction,
            policy,
        )
        proof[profile] = {
            "prediction_mode": prediction.prediction_mode,
            "history_count": prediction.history_count,
            "q97_paise": prediction.amount_for_quantile("0.97").amount_paise,
            "recommended_block_paise": decision.recommended_block.amount_paise,
        }
    return proof


def _artifact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        "model_version": metadata["model_version"],
        "dataset_fingerprint_sha256": metadata["dataset_fingerprint_sha256"],
        "library_versions": metadata["library_versions"],
        "trusted_sources_only": metadata["trusted_sources_only"],
    }


def generate_final_evidence(config: FinalEvidenceConfig) -> dict[str, object]:
    """Generate, validate, and persist the complete Phase-13 evidence artifact."""

    dataset = generate_dataset(
        count=config.transaction_count,
        seed=config.dataset_seed,
        customer_pool_size=config.customer_pool_size,
    )
    if len(dataset.records) != config.transaction_count:
        raise ValueError("generated evidence dataset count does not match configuration")
    base_artifact = load_predictor_artifact(config.base_model_path)
    personalized_artifact = load_personalized_artifact(config.personalized_model_path)
    history = InMemoryCustomerHistoryProvider(dataset.transactions, dataset.outcomes)
    predictor = _AuditablePersonalizedPredictor(
        base_artifact.model,
        personalized_artifact.model,
        history,
    )
    optimizer = ReserveBlockOptimizer()
    policy = ReserveRiskPolicy.for_profile(RiskProfile(config.primary_risk_profile))
    optimized = OptimizedReserveStrategy(predictor, optimizer, policy)
    strategies = (ExactEstimateStrategy(), FixedBufferStrategy(), optimized)
    comparison = compare_strategies(dataset.transactions, dataset.outcomes, strategies)
    strategy_metrics = {
        metric.strategy: metric.to_dict() for metric in comparison.metrics
    }
    for metric in strategy_metrics.values():
        metric["average_block_amount_paise"] = (
            int(metric["total_blocked_amount_paise"])
            // int(metric["transaction_count"])
        )

    evaluations_by_strategy = _strategy_evaluations(dataset, strategies, optimized)
    confidence = {
        name: _strategy_confidence(
            evaluations,
            seed=config.bootstrap_seed + index,
            samples=config.bootstrap_samples,
        )
        for index, (name, evaluations) in enumerate(evaluations_by_strategy.items())
    }

    prediction_records = build_prediction_records(dataset.transactions, dataset.outcomes)
    # Populate the cache even if a future strategy implementation becomes lazy.
    for record in prediction_records:
        predictor.predict(record.context)
    prediction_metrics = calculate_prediction_metrics(
        prediction_records,
        lambda record: predictor.raw_by_transaction[record.context.transaction_id],
    )
    mode_counts = Counter(
        item.prediction_mode for item in predictor.predictions.values()
    )

    dynamic_config = SimulationConfig(
        transaction_count=config.dynamic_record_count,
        seed=config.dynamic_seed,
        customer_pool_size=min(
            config.customer_pool_size, max(25, config.dynamic_record_count // 4)
        ),
        customer_behavior_enabled=True,
    )
    dynamic_dataset = simulate_dynamic_transactions(dynamic_config)
    dynamic_history = InMemoryCustomerHistoryProvider(
        dynamic_dataset.transactions, dynamic_dataset.outcomes
    )
    dynamic_predictor = _AuditablePersonalizedPredictor(
        base_artifact.model,
        personalized_artifact.model,
        dynamic_history,
    )
    dynamic_evidence = evaluate_dynamic_reoptimization(
        dynamic_dataset,
        DynamicRideService(dynamic_predictor, optimizer),
        policy,
    ).to_dict()

    agent_report = evaluate_agent_orchestration(
        dataset.transactions[: config.agent_record_count],
        base_artifact.model,
        personalized_artifact.model,
        history,
        risk_profile=policy.profile,
    )

    exact = strategy_metrics["exact_estimate"]
    fixed = strategy_metrics["fixed_buffer_20"]
    selected = strategy_metrics[f"optimized_{policy.profile.value}"]
    optimized_blocks = tuple(
        item.recommended_block.amount_paise
        for item in optimized.optimization_results
    )
    deltas = {
        "optimized_collection_success_percentage_points_vs_exact": format(
            (
                Decimal(str(selected["collection_success_rate"]))
                - Decimal(str(exact["collection_success_rate"]))
            )
            * Decimal(100),
            ".3f",
        ),
        "optimized_average_excess_reduction_paise_vs_fixed_20": (
            int(fixed["average_excess_block_paise"])
            - int(selected["average_excess_block_paise"])
        ),
    }
    dashboard_deltas = {
        "collection_success_percentage_points_vs_exact": deltas[
            "optimized_collection_success_percentage_points_vs_exact"
        ],
        "average_excess_reduction_paise_vs_fixed_20": deltas[
            "optimized_average_excess_reduction_paise_vs_fixed_20"
        ],
    }
    per_city = _per_city(dataset, evaluations_by_strategy)
    personalization = _personalization_proof(
        base_artifact.model, personalized_artifact.model, optimizer, policy
    )
    artifact: dict[str, object] = {
        "evidence_status": "complete",
        "phase": 13,
        "provenance": {
            "project_version": __version__,
            "dataset": "Synthetic India Mobility",
            "record_count": config.transaction_count,
            "seed": config.dataset_seed,
            "predictor": personalized_artifact.model.model_version,
            "policy": policy.profile.value,
            "target_collection_probability": format_ratio(
                policy.target_collection_probability
            ),
            "synthetic_data_disclaimer": (
                "These results use synthetic city profiles and are not production city statistics."
            ),
            "synthetic_data_only": True,
            "production_data_used": False,
            "dataset_fingerprint_sha256": dataset_fingerprint(dataset),
            "configuration": config.to_dict(),
            "base_model": _artifact_metadata(base_artifact.metadata),
            "personalized_model": _artifact_metadata(personalized_artifact.metadata),
            "evaluation_dataset_used_for_training": False,
            "retraining_performed": False,
            "filesystem_paths_in_fingerprint": False,
        },
        "strategy_comparison": {
            "scope": "same_fresh_transactions_and_outcomes",
            "metrics": strategy_metrics,
            "confidence_intervals_95": confidence,
            "deltas": deltas,
        },
        "prediction_calibration": {
            **prediction_metrics.to_dict(),
            "prediction_mode_counts": dict(sorted(mode_counts.items())),
            "interpretation": (
                "Observed coverage is empirical calibration on fresh synthetic data, "
                "not a guarantee for future transactions."
            ),
        },
        "per_city": per_city,
        "dynamic_reoptimization": {
            "dataset_seed": config.dynamic_seed,
            **dynamic_evidence,
        },
        "agent_consistency": {
            "record_count": agent_report.total_records,
            "successful_runs": agent_report.successful_runs,
            "decision_mismatches": agent_report.decision_mismatches,
            "average_tool_calls": agent_report.average_tool_calls,
            "financial_equivalence_required": True,
        },
        # Dashboard-ready aliases keep the UI a pure presenter while the
        # authoritative nested sections remain explicit and machine-readable.
        "strategies": strategy_metrics,
        "deltas": dashboard_deltas,
        "block_distribution": _histogram(optimized_blocks),
        "tradeoff_points": [
            {
                "strategy": name,
                "average_excess_block_paise": values["average_excess_block_paise"],
                "collection_success_rate": values["collection_success_rate"],
            }
            for name, values in strategy_metrics.items()
        ],
        "personalization": personalization,
        "dynamic": dynamic_evidence,
        "limitations": [
            "All evaluated rides are generated by the deterministic synthetic simulator.",
            "No Razorpay, merchant, Uber, Ola, or production customer data is used.",
            "Observed calibration and success rates are empirical estimates, not guarantees.",
            "Dynamic evaluation assumes recommended mock authorizations succeed.",
            "Merchant-history personalization is unavailable.",
        ],
    }
    validate_final_evidence(artifact, config)
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def validate_final_evidence(
    artifact: dict[str, object], config: FinalEvidenceConfig
) -> None:
    """Fail closed if an authoritative artifact is incomplete or inconsistent."""

    if artifact.get("evidence_status") != "complete":
        raise ValueError("final evidence status must be complete")
    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("final evidence requires provenance")
    configuration = provenance.get("configuration")
    if not isinstance(configuration, dict) or configuration.get("transaction_count") != config.transaction_count:
        raise ValueError("final evidence transaction count does not match configuration")
    if config.transaction_count < 10_000:
        raise ValueError("authoritative evidence requires at least 10,000 records")
    fingerprint = provenance.get("dataset_fingerprint_sha256")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("final evidence requires a canonical SHA-256 fingerprint")
    for model_key in ("base_model", "personalized_model"):
        metadata = provenance.get(model_key)
        if not isinstance(metadata, dict) or not metadata.get("trusted_sources_only"):
            raise ValueError(f"final evidence requires trusted {model_key} metadata")
    comparison = artifact.get("strategy_comparison")
    if not isinstance(comparison, dict) or not isinstance(comparison.get("metrics"), dict):
        raise ValueError("final evidence requires strategy metrics")
    required = {"exact_estimate", "fixed_buffer_20", f"optimized_{config.primary_risk_profile}"}
    if set(comparison["metrics"]) != required:
        raise ValueError("final evidence strategy set is incomplete")
    confidence = comparison.get("confidence_intervals_95")
    if not isinstance(confidence, dict) or set(confidence) != required:
        raise ValueError("final evidence confidence intervals are incomplete")
    calibration = artifact.get("prediction_calibration")
    if not isinstance(calibration, dict) or not isinstance(calibration.get("quantiles"), dict):
        raise ValueError("final evidence requires quantile calibration")
    if set(calibration["quantiles"]) != {f"{value:.2f}" for value in QUANTILES}:
        raise ValueError("final evidence quantile calibration is incomplete")
    if calibration.get("record_count") != config.transaction_count:
        raise ValueError("final evidence calibration count is inconsistent")
    per_city = artifact.get("per_city")
    expected_cities = {
        "delhi", "mumbai", "bengaluru", "hyderabad", "pune", "chennai", "kolkata"
    }
    if not isinstance(per_city, dict) or set(per_city) != expected_cities:
        raise ValueError("final evidence per-city diagnostics are incomplete")
    dynamic = artifact.get("dynamic_reoptimization")
    if not isinstance(dynamic, dict) or dynamic.get("record_count") != config.dynamic_record_count:
        raise ValueError("final evidence dynamic cohort is inconsistent")
    agent = artifact.get("agent_consistency")
    if not isinstance(agent, dict) or agent.get("decision_mismatches") != 0:
        raise ValueError("agent decisions must match direct service decisions")
    if agent.get("record_count") != config.agent_record_count:
        raise ValueError("final evidence agent cohort is inconsistent")
    dashboard_keys = {
        "strategies", "block_distribution", "tradeoff_points", "personalization", "dynamic"
    }
    if not dashboard_keys.issubset(artifact):
        raise ValueError("final evidence dashboard projection is incomplete")
