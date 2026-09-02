"""Deprecated Phase-11 regression fixture generator.

The sole authoritative artifact is produced by ``evidence.pipeline``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
from pathlib import Path

from reserve_pay_optimizer import __version__
from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.dynamic.evaluation import evaluate_dynamic_reoptimization
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.dynamic.simulation import simulate_dynamic_transactions
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import InMemoryCustomerHistoryProvider
from reserve_pay_optimizer.personalization.persistence import load_personalized_artifact
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.persistence import load_predictor_artifact
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.evaluation import aggregate_evaluations, evaluate_transaction
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from reserve_pay_optimizer.strategies.optimized import OptimizedReserveStrategy
from reserve_pay_optimizer.web.schemas import OptimizeRequest
from reserve_pay_optimizer.web.services import DashboardService, DashboardSettings

DEFAULT_EVIDENCE_SEED = 202611
DEFAULT_EVIDENCE_COUNT = 10_000
DEFAULT_DYNAMIC_EVIDENCE_COUNT = 500
DEFAULT_DYNAMIC_EVIDENCE_SEED = 202612


def _dataset_fingerprint(dataset) -> str:
    digest = sha256()
    for record in dataset.records:
        payload = (
            record.transaction.transaction_id,
            record.transaction.customer_id,
            record.transaction.estimated_amount.amount_paise,
            record.transaction.city.value,
            str(record.transaction.distance_km),
            record.transaction.estimated_duration_minutes,
            str(record.transaction.surge_multiplier),
            record.transaction.timestamp.isoformat(),
            record.outcome.actual_amount.amount_paise,
            record.outcome.completed_at.isoformat(),
        )
        digest.update(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def _histogram(values: list[int], bin_count: int = 14) -> list[dict[str, int]]:
    lower = min(values)
    upper = max(values)
    width = max(
        1,
        int(
            (Decimal(upper - lower + 1) / Decimal(bin_count)).to_integral_value(
                rounding=ROUND_CEILING
            )
        ),
    )
    bins = [0] * bin_count
    for value in values:
        index = min((value - lower) // width, bin_count - 1)
        bins[index] += 1
    return [
        {
            "lower_paise": lower + index * width,
            "upper_paise": lower + (index + 1) * width - 1,
            "count": count,
        }
        for index, count in enumerate(bins)
    ]


def prepare_dashboard_evidence(
    *,
    count: int = DEFAULT_EVIDENCE_COUNT,
    seed: int = DEFAULT_EVIDENCE_SEED,
    output: Path,
    settings: DashboardSettings | None = None,
) -> dict[str, object]:
    resolved = settings or DashboardSettings()
    config = SimulationConfig(
        transaction_count=count,
        seed=seed,
        customer_pool_size=max(25, min(1_000, count // 10)),
        customer_behavior_enabled=True,
    )
    dataset = simulate_transactions(config)
    base = load_predictor_artifact(resolved.resolved_base_model)
    personalized = load_personalized_artifact(resolved.resolved_personalized_model)
    history = InMemoryCustomerHistoryProvider(dataset.transactions, dataset.outcomes)
    predictor = PersonalizedFarePredictor(base.model, personalized.model, history)
    optimizer = ReserveBlockOptimizer()
    policy = ReserveRiskPolicy.for_profile(RiskProfile.BALANCED)
    optimized = OptimizedReserveStrategy(predictor, optimizer, policy)
    comparison = compare_strategies(
        dataset.transactions,
        dataset.outcomes,
        (ExactEstimateStrategy(), FixedBufferStrategy(), optimized),
    )
    strategies = {metric.strategy: metric.to_dict() for metric in comparison.metrics}
    for metric in strategies.values():
        metric["average_block_amount_paise"] = int(metric["total_blocked_amount_paise"]) // int(metric["transaction_count"])
    optimized_results = {
        result.transaction_id: result for result in optimized.optimization_results
    }
    outcomes = {outcome.transaction_id: outcome for outcome in dataset.outcomes}
    per_city: dict[str, object] = {}
    for city in sorted({item.city for item in dataset.transactions}, key=lambda item: item.value):
        evaluations = [
            evaluate_transaction(
                transaction,
                optimized_results[transaction.transaction_id].reserve_decision,
                outcomes[transaction.transaction_id],
            )
            for transaction in dataset.transactions
            if transaction.city is city
        ]
        metrics = aggregate_evaluations(evaluations)
        per_city[city.value] = {
            "record_count": len(evaluations),
            "optimized_collection_success_rate": format_ratio(metrics.collection_success_rate),
            "optimized_average_excess_block_paise": metrics.average_excess_block.amount_paise,
        }
    block_amounts = [
        result.recommended_block.amount_paise
        for result in optimized.optimization_results
    ]
    dashboard_service = DashboardService(resolved)
    personalization = {}
    for profile in ("stable_history", "overrun_prone"):
        response = dashboard_service.optimize(
            OptimizeRequest(customer_profile=profile)  # type: ignore[arg-type]
        )
        prediction = response["prediction"]
        decision = response["decision"]
        assert isinstance(prediction, dict) and isinstance(decision, dict)
        quantiles = prediction["quantiles_paise"]
        assert isinstance(quantiles, dict)
        personalization[profile] = {
            "prediction_mode": prediction["mode"],
            "history_count": prediction["history_count"],
            "q97_paise": quantiles["0.97"],
            "recommended_block_paise": decision["recommended_block_paise"],
        }
    dynamic_config = SimulationConfig(
        transaction_count=min(DEFAULT_DYNAMIC_EVIDENCE_COUNT, max(20, count)),
        seed=DEFAULT_DYNAMIC_EVIDENCE_SEED,
        customer_pool_size=min(100, max(10, count // 20)),
        customer_behavior_enabled=True,
    )
    dynamic_dataset = simulate_dynamic_transactions(dynamic_config)
    dynamic_history = InMemoryCustomerHistoryProvider(
        dynamic_dataset.transactions, dynamic_dataset.outcomes
    )
    dynamic_predictor = PersonalizedFarePredictor(
        base.model, personalized.model, dynamic_history
    )
    dynamic_evaluation = evaluate_dynamic_reoptimization(
        dynamic_dataset,
        DynamicRideService(dynamic_predictor, optimizer),
        policy,
    ).to_dict()
    exact = strategies["exact_estimate"]
    fixed = strategies["fixed_buffer_20"]
    optimized_metrics = strategies["optimized_balanced"]
    artifact: dict[str, object] = {
        "deprecated": True,
        "authoritative_artifact": "demo/evidence/final_evidence.json",
        "provenance": {
            "dataset": "Synthetic India Mobility",
            "record_count": count,
            "seed": seed,
            "customer_pool_size": config.customer_pool_size,
            "customer_behavior_enabled": True,
            "dataset_fingerprint_sha256": _dataset_fingerprint(dataset),
            "predictor": personalized.model.model_version,
            "base_predictor": base.model.model_version,
            "policy": "balanced",
            "target_collection_probability": "0.970000",
            "project_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
            "synthetic_data_disclaimer": "These results use synthetic city profiles and are not production city statistics.",
        },
        "strategies": strategies,
        "deltas": {
            "collection_success_percentage_points_vs_exact": format(
                (Decimal(str(optimized_metrics["collection_success_rate"])) - Decimal(str(exact["collection_success_rate"]))) * Decimal(100),
                ".3f",
            ),
            "average_excess_reduction_paise_vs_fixed_20": int(fixed["average_excess_block_paise"]) - int(optimized_metrics["average_excess_block_paise"]),
        },
        "block_distribution": _histogram(block_amounts),
        "tradeoff_points": [
            {
                "strategy": key,
                "average_excess_block_paise": value["average_excess_block_paise"],
                "collection_success_rate": value["collection_success_rate"],
            }
            for key, value in strategies.items()
        ],
        "per_city": per_city,
        "personalization": personalization,
        "dynamic": dynamic_evaluation,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact
