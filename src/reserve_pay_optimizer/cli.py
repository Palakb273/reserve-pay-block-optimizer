"""Command-line workflows for domain, simulation, prediction, and personalization."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections.abc import Mapping
from typing import Sequence, TextIO

from reserve_pay_optimizer.config import MOBILITY_DOMAIN, SUPPORTED_CURRENCY
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.dynamic.errors import DynamicSessionError
from reserve_pay_optimizer.dynamic.evaluation import evaluate_dynamic_reoptimization
from reserve_pay_optimizer.dynamic.serialization import (
    parse_dynamic_dataset,
    parse_dynamic_scenario,
)
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.dynamic.simulation import simulate_dynamic_transactions
from reserve_pay_optimizer.explainability.models import ExplanationLevel
from reserve_pay_optimizer.explainability.service import ExplanationService
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.errors import PolicyTargetNotReachable
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile, built_in_policies
from reserve_pay_optimizer.personalization.dataset import (
    build_personalized_records,
    chronological_split,
    personalized_dataset_fingerprint,
)
from reserve_pay_optimizer.personalization.evaluation import evaluate_personalization
from reserve_pay_optimizer.personalization.history import InMemoryCustomerHistoryProvider
from reserve_pay_optimizer.personalization.persistence import (
    load_personalized_artifact,
    save_personalized_artifact,
)
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.personalization.training import train_personalized_predictor
from reserve_pay_optimizer.prediction.config import ModelConfig
from reserve_pay_optimizer.prediction.dataset import (
    build_prediction_records,
    dataset_fingerprint,
    split_records,
)
from reserve_pay_optimizer.prediction.evaluation import evaluate_predictor
from reserve_pay_optimizer.prediction.persistence import (
    load_predictor_artifact,
    save_predictor_artifact,
)
from reserve_pay_optimizer.prediction.training import train_predictor
from reserve_pay_optimizer.reserve_pay.errors import ReservePayError
from reserve_pay_optimizer.reserve_pay.mock_provider import (
    MockFailureConfig,
    MockReserveProvider,
)
from reserve_pay_optimizer.reserve_pay.models import GetBlockStatusRequest
from reserve_pay_optimizer.reserve_pay.razorpay_provider import (
    RazorpayProvider,
    RazorpayProviderConfig,
)
from reserve_pay_optimizer.reserve_pay.service import ReservePayService, RetryConfig
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.evaluation_input import parse_evaluation_dataset
from reserve_pay_optimizer.services.mobility_validation import (
    parse_mobility_transaction,
    validate_mobility_transaction,
)
from reserve_pay_optimizer.services.optimizer_evaluation import evaluate_optimizer_strategies
from reserve_pay_optimizer.services.policy_evaluation import evaluate_risk_profiles
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy


def _datetime_argument(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a valid RFC 3339 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("must include a UTC offset")
    return parsed


def _decimal_argument(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be a decimal number") from exc
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("must be finite")
    return parsed


def _add_optimization_arguments(parser: argparse.ArgumentParser) -> None:
    defaults = OptimizationConfig()
    parser.add_argument("--lambda-under", type=_decimal_argument, default=defaults.lambda_under)
    parser.add_argument("--lambda-excess", type=_decimal_argument, default=defaults.lambda_excess)
    parser.add_argument("--lambda-friction", type=_decimal_argument, default=defaults.lambda_friction)
    parser.add_argument("--candidate-step-paise", type=int, default=defaults.candidate_step_paise)


def _optimization_config(args: argparse.Namespace) -> OptimizationConfig:
    return OptimizationConfig(
        lambda_under=args.lambda_under,
        lambda_excess=args.lambda_excess,
        lambda_friction=args.lambda_friction,
        candidate_step_paise=args.candidate_step_paise,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reserve-pay-optimizer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-mobility",
        help="validate and normalize a Phase 1 ride transaction context",
    )
    validate.add_argument(
        "--file",
        type=Path,
        help="JSON input file; omit to read JSON from standard input",
    )
    evaluate = subparsers.add_parser(
        "evaluate-baselines",
        help="compare Phase 2 exact-estimate and fixed-buffer baselines",
    )
    evaluate.add_argument(
        "--file",
        type=Path,
        help="evaluation dataset JSON file; omit to read JSON from standard input",
    )
    simulate = subparsers.add_parser(
        "simulate-mobility",
        help="generate deterministic synthetic India mobility transactions",
    )
    simulate.add_argument("--count", type=int, default=100)
    simulate.add_argument("--seed", type=int, default=42)
    simulate.add_argument("--customer-pool-size", type=int, default=25)
    simulate.add_argument("--start-datetime", type=_datetime_argument)
    simulate.add_argument("--end-datetime", type=_datetime_argument)
    simulate.add_argument(
        "--personalized-customer-behavior",
        action="store_true",
        help="opt into hidden deterministic synthetic customer behavior",
    )
    simulate.add_argument(
        "--output",
        type=Path,
        help="write dataset JSON here; omit to write the dataset to standard output",
    )
    train = subparsers.add_parser(
        "train-predictor",
        help="train Phase 4 conditional final-fare quantile models",
    )
    train.add_argument("--file", type=Path, required=True, help="simulation/evaluation dataset JSON")
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--output", type=Path, required=True, help="trusted project-local artifact directory")
    evaluate_predictor_parser = subparsers.add_parser(
        "evaluate-predictor",
        help="evaluate a trusted Phase 4 artifact against completed records",
    )
    evaluate_predictor_parser.add_argument("--file", type=Path, required=True)
    evaluate_predictor_parser.add_argument("--model", type=Path, required=True)
    predict = subparsers.add_parser(
        "predict-distribution",
        help="predict monotonic final-fare quantiles for one ride context",
    )
    predict.add_argument("--model", type=Path, required=True)
    predict.add_argument("--file", type=Path, required=True)
    optimize = subparsers.add_parser(
        "optimize-block",
        help="recommend one reserve block from a trusted fare-distribution model",
    )
    optimize.add_argument("--model", type=Path, required=True)
    optimize.add_argument("--file", type=Path, required=True)
    optimize.add_argument("--verbose", action="store_true", help="include the five best candidate scores")
    optimize.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        help="apply a Phase-6 merchant policy; omit to preserve unconstrained Phase-5 behavior",
    )
    _add_optimization_arguments(optimize)
    evaluate_optimizer = subparsers.add_parser(
        "evaluate-optimizer",
        help="compare exact, fixed-buffer, and optimized reserve strategies",
    )
    evaluate_optimizer.add_argument("--model", type=Path, required=True)
    evaluate_optimizer.add_argument("--file", type=Path, required=True)
    _add_optimization_arguments(evaluate_optimizer)
    compare_profiles = subparsers.add_parser(
        "compare-risk-profiles",
        help="optimize one transaction under aggressive, balanced, and conservative policies",
    )
    compare_profiles.add_argument("--model", type=Path, required=True)
    compare_profiles.add_argument("--file", type=Path, required=True)
    _add_optimization_arguments(compare_profiles)
    evaluate_profiles = subparsers.add_parser(
        "evaluate-risk-profiles",
        help="compare baselines and all three merchant policies on completed records",
    )
    evaluate_profiles.add_argument("--model", type=Path, required=True)
    evaluate_profiles.add_argument("--file", type=Path, required=True)
    _add_optimization_arguments(evaluate_profiles)
    train_personalized = subparsers.add_parser(
        "train-personalized-predictor",
        help="train Phase-7 quantile models using chronological customer history",
    )
    train_personalized.add_argument("--file", type=Path, required=True)
    train_personalized.add_argument("--seed", type=int, default=42)
    train_personalized.add_argument("--base-model", type=Path, required=True)
    train_personalized.add_argument("--output", type=Path, required=True)
    evaluate_personalized = subparsers.add_parser(
        "evaluate-personalization",
        help="compare base and personalized models on the chronological test set",
    )
    evaluate_personalized.add_argument("--file", type=Path, required=True)
    evaluate_personalized.add_argument("--model", type=Path, required=True)
    evaluate_personalized.add_argument("--base-model", type=Path, required=True)
    predict_personalized = subparsers.add_parser(
        "predict-personalized-distribution",
        help="predict with automatically selected base/personalized mode",
    )
    predict_personalized.add_argument("--model", type=Path, required=True)
    predict_personalized.add_argument("--base-model", type=Path, required=True)
    predict_personalized.add_argument("--history", type=Path, required=True)
    predict_personalized.add_argument("--file", type=Path, required=True)
    optimize_personalized = subparsers.add_parser(
        "optimize-personalized-block",
        help="feed a history-aware distribution into the existing policy optimizer",
    )
    optimize_personalized.add_argument("--model", type=Path, required=True)
    optimize_personalized.add_argument("--base-model", type=Path, required=True)
    optimize_personalized.add_argument("--history", type=Path, required=True)
    optimize_personalized.add_argument("--file", type=Path, required=True)
    optimize_personalized.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    optimize_personalized.add_argument("--verbose", action="store_true")
    _add_optimization_arguments(optimize_personalized)
    compare_customers = subparsers.add_parser(
        "compare-customer-personalization",
        help="compare two same-ride customer histories through prediction and policy",
    )
    compare_customers.add_argument("--model", type=Path, required=True)
    compare_customers.add_argument("--base-model", type=Path, required=True)
    compare_customers.add_argument("--scenario", type=Path, required=True)
    compare_customers.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    _add_optimization_arguments(compare_customers)
    simulate_dynamic = subparsers.add_parser(
        "simulate-dynamic-mobility",
        help="generate deterministic rides with observable in-ride context updates",
    )
    simulate_dynamic.add_argument("--count", type=int, default=100)
    simulate_dynamic.add_argument("--seed", type=int, default=202608)
    simulate_dynamic.add_argument("--customer-pool-size", type=int, default=25)
    simulate_dynamic.add_argument(
        "--personalized",
        action="store_true",
        help="enable hidden synthetic customer behavior without exporting it",
    )
    simulate_dynamic.add_argument("--output", type=Path)
    run_dynamic = subparsers.add_parser(
        "run-dynamic-ride",
        help="run one dynamic ride scenario without any payment-provider call",
    )
    run_dynamic.add_argument("--model", type=Path, required=True)
    run_dynamic.add_argument("--base-model", type=Path, required=True)
    run_dynamic.add_argument("--scenario", type=Path, required=True)
    run_dynamic.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    run_dynamic.add_argument(
        "--auto-confirm",
        action="store_true",
        help="simulate successful authorization of each recommended increase",
    )
    run_dynamic.add_argument("--verbose", action="store_true")
    run_dynamic.add_argument(
        "--explain",
        action="store_true",
        help="attach deterministic structured and rendered explanations",
    )
    run_dynamic.add_argument(
        "--detail",
        choices=[level.value for level in ExplanationLevel],
        default=ExplanationLevel.CONCISE.value,
    )
    _add_optimization_arguments(run_dynamic)
    evaluate_dynamic = subparsers.add_parser(
        "evaluate-dynamic-reoptimization",
        help="compare static and dynamic personalized blocking on identical rides",
    )
    evaluate_dynamic.add_argument("--file", type=Path, required=True)
    evaluate_dynamic.add_argument("--model", type=Path, required=True)
    evaluate_dynamic.add_argument("--base-model", type=Path, required=True)
    evaluate_dynamic.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    _add_optimization_arguments(evaluate_dynamic)
    explain_block = subparsers.add_parser(
        "explain-block",
        help="predict, optimize, and explain one already-computed reserve recommendation",
    )
    explain_block.add_argument("--model", type=Path, required=True)
    explain_block.add_argument("--base-model", type=Path, required=True)
    explain_block.add_argument("--history", type=Path, required=True)
    explain_block.add_argument("--file", type=Path, required=True)
    explain_block.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    explain_block.add_argument(
        "--detail",
        choices=[level.value for level in ExplanationLevel],
        default=ExplanationLevel.CONCISE.value,
    )
    _add_optimization_arguments(explain_block)
    reserve_pay_demo = subparsers.add_parser(
        "reserve-pay-demo",
        help="run the complete Phase-10 Reserve Pay lifecycle",
    )
    reserve_pay_demo.add_argument(
        "--provider", choices=("mock", "razorpay"), default="mock"
    )
    reserve_pay_demo.add_argument("--model", type=Path, required=True)
    reserve_pay_demo.add_argument("--base-model", type=Path, required=True)
    reserve_pay_demo.add_argument("--scenario", type=Path, required=True)
    reserve_pay_demo.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    reserve_pay_demo.add_argument(
        "--fail-first-increase",
        action="store_true",
        help="make the first mock increase fail permanently",
    )
    reserve_pay_demo.add_argument(
        "--retry-first-increase",
        action="store_true",
        help="make the first mock increase transiently fail, then succeed on retry",
    )
    reserve_pay_demo.add_argument("--explain", action="store_true")
    reserve_pay_demo.add_argument("--verbose", action="store_true")
    reserve_pay_demo.add_argument(
        "--detail",
        choices=[level.value for level in ExplanationLevel],
        default=ExplanationLevel.CONCISE.value,
    )
    _add_optimization_arguments(reserve_pay_demo)
    prepare_evidence = subparsers.add_parser(
        "prepare-dashboard-evidence",
        help="precompute deterministic Phase-11 dashboard evidence",
    )
    prepare_evidence.add_argument("--count", type=int, default=10_000)
    prepare_evidence.add_argument("--seed", type=int, default=202611)
    prepare_evidence.add_argument(
        "--output",
        type=Path,
        default=Path("demo/evidence/dashboard_evidence.json"),
    )
    final_evidence = subparsers.add_parser(
        "prepare-final-evidence",
        help="generate the authoritative Phase-13 evaluation artifact",
    )
    final_evidence.add_argument("--count", type=int, default=20_000)
    final_evidence.add_argument("--seed", type=int, default=202_613)
    final_evidence.add_argument("--customer-pool-size", type=int, default=5_000)
    final_evidence.add_argument("--dynamic-count", type=int, default=5_000)
    final_evidence.add_argument("--dynamic-seed", type=int, default=202_714)
    final_evidence.add_argument("--agent-count", type=int, default=500)
    final_evidence.add_argument("--bootstrap-samples", type=int, default=1_000)
    final_evidence.add_argument("--bootstrap-seed", type=int, default=202_815)
    final_evidence.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    final_evidence.add_argument(
        "--base-model",
        type=Path,
        default=Path("artifacts/prediction/fare_distribution_v1"),
    )
    final_evidence.add_argument(
        "--model",
        type=Path,
        default=Path("artifacts/prediction/fare_distribution_personalized_v1"),
    )
    final_evidence.add_argument(
        "--output",
        type=Path,
        default=Path("demo/evidence/final_evidence.json"),
    )
    serve_dashboard = subparsers.add_parser(
        "serve-dashboard",
        help="serve the Phase-11 FastAPI dashboard adapter",
    )
    serve_dashboard.add_argument("--host", default="127.0.0.1")
    serve_dashboard.add_argument("--port", type=int, default=8000)
    agent_decide = subparsers.add_parser(
        "agent-decide",
        help="orchestrate Reserve Intelligence Agent tools to obtain a reserve decision",
    )
    agent_decide.add_argument("--model", type=Path, required=True)
    agent_decide.add_argument("--base-model", type=Path, required=True)
    agent_decide.add_argument("--history", type=Path, required=True)
    agent_decide.add_argument("--file", type=Path, required=True)
    agent_decide.add_argument(
        "--risk-profile",
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    agent_decide.add_argument("--show-trace", action="store_true", help="include the tool audit trace")
    _add_optimization_arguments(agent_decide)
    return parser


def _load_payload(stream: TextIO) -> object:
    return json.load(stream, parse_float=Decimal)


def _error_response(error: DomainValidationError) -> dict[str, object]:
    response = error.to_dict()
    response.update(
        {
            "domain": MOBILITY_DOMAIN.value,
            "currency": SUPPORTED_CURRENCY.value,
        }
    )
    return response


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare-final-evidence":
            from reserve_pay_optimizer.evidence import (
                FinalEvidenceConfig,
                generate_final_evidence,
            )

            evidence_config = FinalEvidenceConfig(
                transaction_count=args.count,
                dataset_seed=args.seed,
                customer_pool_size=args.customer_pool_size,
                dynamic_seed=args.dynamic_seed,
                dynamic_record_count=args.dynamic_count,
                agent_record_count=args.agent_count,
                bootstrap_seed=args.bootstrap_seed,
                bootstrap_samples=args.bootstrap_samples,
                primary_risk_profile=args.risk_profile,
                base_model_path=args.base_model,
                personalized_model_path=args.model,
                output_path=args.output,
            )
            artifact = generate_final_evidence(evidence_config)
            comparison = artifact["primary_strategy_comparison"]
            assert isinstance(comparison, dict)
            result = {
                "evidence_status": "complete",
                "output": str(args.output),
                "summary_output": str(args.output.with_name(f"{args.output.stem}_summary.md")),
                "metadata": artifact["metadata"],
                "strategy_metrics": comparison["metrics"],
                "agent_consistency": artifact["agents"],
            }
        elif args.command == "prepare-dashboard-evidence":
            from reserve_pay_optimizer.web.evidence import prepare_dashboard_evidence

            if args.count <= 0:
                raise ValueError("count must be positive")
            artifact = prepare_dashboard_evidence(
                count=args.count,
                seed=args.seed,
                output=args.output,
            )
            result = {
                "evidence_status": "complete",
                "output": str(args.output),
                "provenance": artifact["provenance"],
                "strategies": artifact["strategies"],
            }
        elif args.command == "serve-dashboard":
            if not 1 <= args.port <= 65535:
                raise ValueError("port must be between 1 and 65535")
            import uvicorn

            uvicorn.run(
                "reserve_pay_optimizer.web.app:app",
                host=args.host,
                port=args.port,
                reload=False,
            )
            return 0
        elif args.command == "agent-decide":
            from reserve_pay_optimizer.agents.models import ReserveAgentRequest
            from reserve_pay_optimizer.agents.orchestrator import AgentOrchestrator

            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            context = parse_mobility_transaction(payload)  # type: ignore[arg-type]
            with args.history.open("r", encoding="utf-8") as stream:
                history_payload = _load_payload(stream)
            history_contexts, history_outcomes = parse_evaluation_dataset(
                history_payload  # type: ignore[arg-type]
            )
            base_artifact = load_predictor_artifact(args.base_model)
            personalized_artifact = load_personalized_artifact(args.model)
            history_provider = InMemoryCustomerHistoryProvider(
                history_contexts, history_outcomes
            )
            optimizer = ReserveBlockOptimizer(_optimization_config(args))
            orchestrator = AgentOrchestrator(
                base_model=base_artifact.model,
                personalized_model=personalized_artifact.model,
                history_provider=history_provider,
                optimizer=optimizer,
            )
            policy = RiskProfile(args.risk_profile)
            response = orchestrator.run(
                ReserveAgentRequest(transaction=context, risk_profile=policy)
            )
            response_dict = response.to_dict()
            if not args.show_trace:
                response_dict.pop("tool_trace", None)
            result = response_dict
        elif args.command == "reserve-pay-demo":
            with args.scenario.open("r", encoding="utf-8") as stream:
                scenario_payload = _load_payload(stream)
            record, history_contexts, history_outcomes = parse_dynamic_scenario(
                scenario_payload  # type: ignore[arg-type]
            )
            personalized_artifact = load_personalized_artifact(args.model)
            base_artifact = load_predictor_artifact(args.base_model)
            predictor = PersonalizedFarePredictor(
                base_artifact.model,
                personalized_artifact.model,
                InMemoryCustomerHistoryProvider(history_contexts, history_outcomes),
            )
            dynamic_service = DynamicRideService(
                predictor, ReserveBlockOptimizer(_optimization_config(args))
            )
            policy = ReserveRiskPolicy.for_profile(RiskProfile(args.risk_profile))
            session = dynamic_service.start_dynamic_session(
                record.initial_transaction, policy
            )
            if args.provider == "mock":
                failure_config = MockFailureConfig(
                    fail_next_increase=args.fail_first_increase,
                    transient_failures={
                        "increase": 1 if args.retry_first_increase else 0
                    },
                )
                provider = MockReserveProvider(failure_config)
            else:
                provider = RazorpayProvider(RazorpayProviderConfig.from_environment())
            audit_tick = 0

            def demo_audit_clock() -> datetime:
                nonlocal audit_tick
                value = record.initial_transaction.timestamp + timedelta(
                    seconds=audit_tick
                )
                audit_tick += 1
                return value

            reserve_service = ReservePayService(
                provider,
                dynamic_service=dynamic_service,
                retry_config=RetryConfig(max_attempts=3, delay_seconds=0),
                sleeper=lambda _: None,
                clock=demo_audit_clock,
            )
            initial_execution = reserve_service.authorize_initial_block(
                session.initial_optimization.reserve_decision,
                customer_reference=session.initial_context.customer_id,
                idempotency_key=f"{session.transaction_id}:initial",
                metadata=(("domain", MOBILITY_DOMAIN.value),),
            )
            if (
                initial_execution.block.authorized_amount
                != session.current_authorized_block
            ):
                raise RuntimeError(
                    "provider initial authorization does not match the computed decision"
                )
            explanation_service = ExplanationService() if args.explain else None
            initial_output: dict[str, object] = {
                "recommendation": session.initial_optimization.to_dict(
                    include_candidates=False
                ),
                "execution": initial_execution.to_dict(),
            }
            if explanation_service is not None:
                initial_output["explanation"] = explanation_service.explain_reserve_decision(
                    session.initial_context,
                    session.initial_prediction,
                    session.initial_optimization,
                    ExplanationLevel(args.detail),
                ).to_dict()
            update_outputs: list[dict[str, object]] = []
            for update in record.updates:
                application = dynamic_service.apply_context_update(session, update)
                session = application.session
                execution = reserve_service.request_additional_block(
                    session,
                    application.decision,
                    block_id=initial_execution.block.block_id,
                    idempotency_key=f"{session.transaction_id}:{update.event_id}:increase",
                )
                session = execution.session
                update_output: dict[str, object] = {
                    "decision": application.decision.to_dict(verbose=args.verbose),
                    "execution": execution.to_dict(),
                }
                if explanation_service is not None:
                    update_output["explanation"] = explanation_service.explain_dynamic_decision(
                        session,
                        application.decision,
                        ExplanationLevel(args.detail),
                    ).to_dict()
                update_outputs.append(update_output)
            settlement = reserve_service.settle_completed_transaction(
                record.outcome,
                block_id=initial_execution.block.block_id,
                idempotency_key=f"{session.transaction_id}:settlement",
            )
            result = {
                "reserve_pay_demo_status": "complete",
                "provider": provider.name.value,
                "transaction_id": session.transaction_id,
                "risk_profile": policy.profile.value,
                "initial": initial_output,
                "updates": update_outputs,
                "completion": settlement.to_dict(),
                "final_block_status": reserve_service.get_block_status(
                    GetBlockStatusRequest(
                        initial_execution.block.block_id, session.transaction_id
                    )
                ).to_dict(),
                "provider_attempts": (
                    [
                        {"operation": operation, "idempotency_key": key}
                        for operation, key in provider.operation_attempts
                    ]
                    if isinstance(provider, MockReserveProvider) and args.verbose
                    else None
                ),
                "audit_events": (
                    [event.to_dict() for event in reserve_service.audit_events]
                    if args.verbose
                    else None
                ),
                "actual_amount_decision_time_use": False,
            }
        elif args.command == "simulate-dynamic-mobility":
            config = SimulationConfig(
                transaction_count=args.count,
                seed=args.seed,
                customer_pool_size=args.customer_pool_size,
                customer_behavior_enabled=args.personalized,
            )
            dataset = simulate_dynamic_transactions(config)
            serialized = dataset.to_dict()
            if args.output is None:
                result = serialized
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(serialized, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                result = {
                    "simulation_status": "complete",
                    "output": str(args.output),
                    **dataset.metadata,
                }
        elif args.command == "run-dynamic-ride":
            with args.scenario.open("r", encoding="utf-8") as stream:
                scenario_payload = _load_payload(stream)
            record, history_contexts, history_outcomes = parse_dynamic_scenario(
                scenario_payload  # type: ignore[arg-type]
            )
            personalized_artifact = load_personalized_artifact(args.model)
            base_artifact = load_predictor_artifact(args.base_model)
            predictor = PersonalizedFarePredictor(
                base_artifact.model,
                personalized_artifact.model,
                InMemoryCustomerHistoryProvider(history_contexts, history_outcomes),
            )
            service = DynamicRideService(
                predictor, ReserveBlockOptimizer(_optimization_config(args))
            )
            policy = ReserveRiskPolicy.for_profile(RiskProfile(args.risk_profile))
            session = service.start_dynamic_session(record.initial_transaction, policy)
            explanation_service = ExplanationService() if args.explain else None
            initial = {
                "estimated_amount_paise": session.initial_context.estimated_amount.amount_paise,
                "q97_paise": session.initial_prediction.amount_for_quantile("0.97").amount_paise,
                "q99_paise": session.initial_prediction.amount_for_quantile("0.99").amount_paise,
                "recommended_and_assumed_authorized_block_paise": session.initial_authorized_block.amount_paise,
                "prediction_mode": session.initial_prediction.prediction_mode,
                "history_count": session.initial_prediction.history_count,
            }
            decisions = []
            for update in record.updates:
                application = service.apply_context_update(session, update)
                session = application.session
                decision = application.decision
                confirmed = False
                if args.auto_confirm and decision.additional_block_required.amount_paise > 0:
                    confirmed_total = Money(
                        session.current_authorized_block.amount_paise
                        + decision.additional_block_required.amount_paise
                    )
                    session = service.confirm_block_authorized(
                        session, decision, confirmed_total
                    )
                    confirmed = True
                decision_output = {
                    **decision.to_dict(verbose=args.verbose),
                    "simulated_authorization_confirmed": confirmed,
                    "authorized_block_after_event_paise": session.current_authorized_block.amount_paise,
                }
                if explanation_service is not None:
                    decision_output["explanation"] = explanation_service.explain_dynamic_decision(
                        session,
                        decision,
                        ExplanationLevel(args.detail),
                    ).to_dict()
                decisions.append(decision_output)
            actual = record.outcome.actual_amount.amount_paise
            result = {
                "dynamic_run_status": "complete",
                "transaction_id": session.transaction_id,
                "risk_profile": policy.profile.value,
                "auto_confirm": args.auto_confirm,
                "payment_provider_called": False,
                "initial": initial,
                "updates": decisions,
                "final_authorized_block_paise": session.current_authorized_block.amount_paise,
                "session": session.to_dict(verbose=args.verbose),
                "retrospective_outcome": {
                    "actual_amount_paise": actual,
                    "completed_at": record.outcome.completed_at.isoformat(),
                    "static_initial_block_would_succeed": (
                        session.initial_authorized_block.amount_paise >= actual
                    ),
                    "dynamic_final_block_would_succeed": (
                        session.current_authorized_block.amount_paise >= actual
                    ),
                    "decision_time_use": False,
                },
            }
            if explanation_service is not None:
                result["explanation_validation_metrics"] = explanation_service.metrics.to_dict()
        elif args.command == "evaluate-dynamic-reoptimization":
            with args.file.open("r", encoding="utf-8") as stream:
                dataset_payload = _load_payload(stream)
            dataset = parse_dynamic_dataset(dataset_payload)  # type: ignore[arg-type]
            personalized_artifact = load_personalized_artifact(args.model)
            base_artifact = load_predictor_artifact(args.base_model)
            provider = InMemoryCustomerHistoryProvider(
                dataset.transactions, dataset.outcomes
            )
            predictor = PersonalizedFarePredictor(
                base_artifact.model, personalized_artifact.model, provider
            )
            service = DynamicRideService(
                predictor, ReserveBlockOptimizer(_optimization_config(args))
            )
            policy = ReserveRiskPolicy.for_profile(RiskProfile(args.risk_profile))
            result = evaluate_dynamic_reoptimization(
                dataset, service, policy
            ).to_dict()
            result["dataset_metadata"] = dataset.metadata
        elif args.command == "explain-block":
            personalized_artifact = load_personalized_artifact(args.model)
            base_artifact = load_predictor_artifact(args.base_model)
            with args.history.open("r", encoding="utf-8") as stream:
                history_payload = _load_payload(stream)
            history_contexts, history_outcomes = parse_evaluation_dataset(history_payload)  # type: ignore[arg-type]
            predictor = PersonalizedFarePredictor(
                base_artifact.model,
                personalized_artifact.model,
                InMemoryCustomerHistoryProvider(history_contexts, history_outcomes),
            )
            with args.file.open("r", encoding="utf-8") as stream:
                transaction_payload = _load_payload(stream)
            context = parse_mobility_transaction(transaction_payload)  # type: ignore[arg-type]
            prediction = predictor.predict(context)
            policy = ReserveRiskPolicy.for_profile(RiskProfile(args.risk_profile))
            optimization = PolicyConstrainedOptimizer(
                ReserveBlockOptimizer(_optimization_config(args))
            ).optimize(context, prediction, policy)
            explanation_service = ExplanationService()
            explanation = explanation_service.explain_reserve_decision(
                context,
                prediction,
                optimization,
                ExplanationLevel(args.detail),
            )
            result = {
                "decision": optimization.to_dict(include_candidates=False),
                "explanation": explanation.to_dict(),
                "explanation_validation_metrics": explanation_service.metrics.to_dict(),
            }
        elif args.command == "simulate-mobility":
            config_kwargs: dict[str, object] = {
                "transaction_count": args.count,
                "seed": args.seed,
                "customer_pool_size": args.customer_pool_size,
                "customer_behavior_enabled": args.personalized_customer_behavior,
            }
            if args.start_datetime is not None:
                config_kwargs["start_datetime"] = args.start_datetime
            if args.end_datetime is not None:
                config_kwargs["end_datetime"] = args.end_datetime
            dataset = simulate_transactions(SimulationConfig(**config_kwargs))
            serialized = dataset.to_dict()
            if args.output is None:
                result = serialized
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(serialized, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                metadata = serialized["metadata"]
                result = {
                    "simulation_status": "complete",
                    "output": str(args.output),
                    "generator": metadata["generator"],
                    "seed": metadata["seed"],
                    "transaction_count": metadata["transaction_count"],
                    "customer_behavior_enabled": args.personalized_customer_behavior,
                    "diagnostics": metadata["diagnostics"],
                }
        elif args.command == "train-personalized-predictor":
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            transactions, outcomes = parse_evaluation_dataset(payload)  # type: ignore[arg-type]
            base_artifact = load_predictor_artifact(args.base_model)
            source_metadata = (
                dict(payload["metadata"])
                if isinstance(payload, Mapping)
                and isinstance(payload.get("metadata"), Mapping)
                else None
            )
            training = train_personalized_predictor(
                transactions,
                outcomes,
                base_artifact.model,
                ModelConfig(seed=args.seed),
                source_metadata=source_metadata,
            )
            save_personalized_artifact(training, args.output)
            result = training.summary(str(args.output))
        elif args.command == "evaluate-personalization":
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            transactions, outcomes = parse_evaluation_dataset(payload)  # type: ignore[arg-type]
            artifact = load_personalized_artifact(args.model)
            base_artifact = load_predictor_artifact(args.base_model)
            records = build_personalized_records(transactions, outcomes)
            split = chronological_split(records, artifact.model.config)
            fingerprint = personalized_dataset_fingerprint(records, artifact.model.config)
            evaluation = evaluate_personalization(
                artifact.model, base_artifact.model, split.test
            )
            result = {
                "evaluation_status": "complete",
                "evaluation_scope": "chronological_test_split",
                "dataset_fingerprint_matches_training_input": (
                    fingerprint == artifact.metadata["dataset_fingerprint_sha256"]
                ),
                "model_version": artifact.model.model_version,
                **evaluation.to_dict(),
            }
        elif args.command in {
            "predict-personalized-distribution",
            "optimize-personalized-block",
        }:
            personalized_artifact = load_personalized_artifact(args.model)
            base_artifact = load_predictor_artifact(args.base_model)
            with args.history.open("r", encoding="utf-8") as stream:
                history_payload = _load_payload(stream)
            history_contexts, history_outcomes = parse_evaluation_dataset(history_payload)  # type: ignore[arg-type]
            provider = InMemoryCustomerHistoryProvider(
                history_contexts, history_outcomes
            )
            predictor = PersonalizedFarePredictor(
                base_artifact.model, personalized_artifact.model, provider
            )
            with args.file.open("r", encoding="utf-8") as stream:
                transaction_payload = _load_payload(stream)
            context = parse_mobility_transaction(transaction_payload)  # type: ignore[arg-type]
            prediction = predictor.predict(context)
            if args.command == "predict-personalized-distribution":
                result = prediction.to_dict()
                if prediction.history_features is not None:
                    result["history_features"] = prediction.history_features.to_dict()
            else:
                policy = ReserveRiskPolicy.for_profile(RiskProfile(args.risk_profile))
                optimization = PolicyConstrainedOptimizer(
                    ReserveBlockOptimizer(_optimization_config(args))
                ).optimize(context, prediction, policy)
                result = optimization.to_dict(include_candidates=args.verbose)
                result.update(
                    {
                        "prediction_mode": prediction.prediction_mode,
                        "history_count": prediction.history_count,
                        "history_as_of": prediction.history_as_of.isoformat()
                        if prediction.history_as_of
                        else None,
                        "history_features": prediction.history_features.to_dict()
                        if prediction.history_features
                        else None,
                    }
                )
        elif args.command == "compare-customer-personalization":
            personalized_artifact = load_personalized_artifact(args.model)
            base_artifact = load_predictor_artifact(args.base_model)
            with args.scenario.open("r", encoding="utf-8") as stream:
                scenario = _load_payload(stream)
            if not isinstance(scenario, Mapping) or not isinstance(
                scenario.get("customers"), Sequence
            ):
                raise ValueError("scenario must contain a customers array")
            policy = ReserveRiskPolicy.for_profile(RiskProfile(args.risk_profile))
            optimizer = PolicyConstrainedOptimizer(
                ReserveBlockOptimizer(_optimization_config(args))
            )
            customers: dict[str, object] = {}
            for index, item in enumerate(scenario["customers"]):
                if not isinstance(item, Mapping):
                    raise ValueError(f"customers[{index}] must be an object")
                label = str(item.get("label", f"customer_{index + 1}"))
                context = parse_mobility_transaction(item.get("transaction"))  # type: ignore[arg-type]
                history_contexts, history_outcomes = parse_evaluation_dataset(
                    item.get("history")  # type: ignore[arg-type]
                )
                predictor = PersonalizedFarePredictor(
                    base_artifact.model,
                    personalized_artifact.model,
                    InMemoryCustomerHistoryProvider(
                        history_contexts, history_outcomes
                    ),
                )
                prediction = predictor.predict(context)
                optimization = optimizer.optimize(context, prediction, policy)
                customers[label] = {
                    "customer_id": context.customer_id,
                    "prediction_mode": prediction.prediction_mode,
                    "history": prediction.history_features.to_dict()
                    if prediction.history_features
                    else None,
                    "q97_paise": prediction.amount_for_quantile("0.97").amount_paise,
                    "q99_paise": prediction.amount_for_quantile("0.99").amount_paise,
                    "recommended_block_paise": optimization.recommended_block.amount_paise,
                    "estimated_collection_probability": format_ratio(
                        optimization.estimated_collection_probability
                    ),
                    "objective_score": format_ratio(optimization.objective_score),
                }
            result = {
                "comparison_status": "complete",
                "risk_profile": policy.profile.value,
                "target_collection_probability": format_ratio(
                    policy.target_collection_probability
                ),
                "customers": customers,
            }
        elif args.command in {"train-predictor", "evaluate-predictor"}:
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            transactions, outcomes = parse_evaluation_dataset(payload)  # type: ignore[arg-type]
            if args.command == "train-predictor":
                training = train_predictor(
                    transactions,
                    outcomes,
                    ModelConfig(seed=args.seed),
                )
                save_predictor_artifact(training, args.output)
                result = training.summary(str(args.output))
            else:
                artifact = load_predictor_artifact(args.model)
                records = build_prediction_records(transactions, outcomes)
                current_fingerprint = dataset_fingerprint(records, artifact.model.config)
                expected_fingerprint = artifact.metadata["dataset_fingerprint_sha256"]
                if current_fingerprint == expected_fingerprint:
                    evaluation_records = split_records(records, artifact.model.config).test
                    scope = "held_out_test_split"
                else:
                    evaluation_records = records
                    scope = "external_all_records"
                evaluation = evaluate_predictor(artifact.model, evaluation_records)
                result = {
                    "evaluation_status": "complete",
                    "evaluation_scope": scope,
                    "dataset_fingerprint_matches_training_input": current_fingerprint == expected_fingerprint,
                    "model_version": artifact.model.model_version,
                    **evaluation.to_dict(),
                }
        elif args.command == "predict-distribution":
            artifact = load_predictor_artifact(args.model)
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            context = parse_mobility_transaction(payload)  # type: ignore[arg-type]
            result = artifact.model.predict(context).to_dict()
        elif args.command == "optimize-block":
            artifact = load_predictor_artifact(args.model)
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            context = parse_mobility_transaction(payload)  # type: ignore[arg-type]
            optimizer = ReserveBlockOptimizer(_optimization_config(args))
            prediction = artifact.model.predict(context)
            if args.risk_profile is None:
                optimization = optimizer.optimize(context, prediction)
            else:
                policy = ReserveRiskPolicy.for_profile(RiskProfile(args.risk_profile))
                optimization = PolicyConstrainedOptimizer(optimizer).optimize(
                    context, prediction, policy
                )
            result = optimization.to_dict(include_candidates=args.verbose)
        elif args.command == "evaluate-optimizer":
            artifact = load_predictor_artifact(args.model)
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            transactions, outcomes = parse_evaluation_dataset(payload)  # type: ignore[arg-type]
            evaluation = evaluate_optimizer_strategies(
                transactions,
                outcomes,
                artifact.model,
                ReserveBlockOptimizer(_optimization_config(args)),
            )
            result = evaluation.to_dict()
            result.update({"domain": MOBILITY_DOMAIN.value, "currency": SUPPORTED_CURRENCY.value})
        elif args.command == "compare-risk-profiles":
            artifact = load_predictor_artifact(args.model)
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            context = parse_mobility_transaction(payload)  # type: ignore[arg-type]
            prediction = artifact.model.predict(context)
            policy_optimizer = PolicyConstrainedOptimizer(
                ReserveBlockOptimizer(_optimization_config(args))
            )
            results = tuple(
                policy_optimizer.optimize(context, prediction, policy)
                for policy in built_in_policies()
            )
            result = {
                "transaction_id": context.transaction_id,
                "model_version": prediction.model_version,
                "profiles": {
                    item.risk_policy.profile.value: item.to_dict()
                    for item in results
                },
            }
        elif args.command == "evaluate-risk-profiles":
            artifact = load_predictor_artifact(args.model)
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
            transactions, outcomes = parse_evaluation_dataset(payload)  # type: ignore[arg-type]
            evaluation = evaluate_risk_profiles(
                transactions,
                outcomes,
                artifact.model,
                ReserveBlockOptimizer(_optimization_config(args)),
            )
            result = evaluation.to_dict()
            result.update({"domain": MOBILITY_DOMAIN.value, "currency": SUPPORTED_CURRENCY.value})
        else:
            if args.file:
                with args.file.open("r", encoding="utf-8") as stream:
                    payload = _load_payload(stream)
            else:
                payload = _load_payload(sys.stdin)
            if args.command == "validate-mobility":
                result = validate_mobility_transaction(payload)  # type: ignore[arg-type]
            elif args.command == "evaluate-baselines":
                transactions, outcomes = parse_evaluation_dataset(payload)  # type: ignore[arg-type]
                comparison = compare_strategies(
                    transactions,
                    outcomes,
                    (ExactEstimateStrategy(), FixedBufferStrategy()),
                )
                result = comparison.to_dict()
                result.update(
                    {
                        "domain": MOBILITY_DOMAIN.value,
                        "currency": SUPPORTED_CURRENCY.value,
                    }
                )
    except json.JSONDecodeError as exc:
        result = _error_response(
            DomainValidationError(
                [ValidationIssue("$", "invalid_json", f"Invalid JSON: {exc.msg}.")]
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    except DomainValidationError as exc:
        print(json.dumps(_error_response(exc), indent=2, sort_keys=True))
        return 2
    except DynamicSessionError as exc:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True))
        return 2
    except PolicyTargetNotReachable as exc:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True))
        return 2
    except ReservePayError as exc:
        print(
            json.dumps(
                {"status": "error", "error_type": "reserve_pay_error", **exc.to_dict()},
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2, sort_keys=True))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
