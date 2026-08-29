"""Command-line workflows for domain, simulation, and prediction phases."""

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence, TextIO

from reserve_pay_optimizer.config import MOBILITY_DOMAIN, SUPPORTED_CURRENCY
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.errors import PolicyTargetNotReachable
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile, built_in_policies
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
        if args.command == "simulate-mobility":
            config_kwargs: dict[str, object] = {
                "transaction_count": args.count,
                "seed": args.seed,
                "customer_pool_size": args.customer_pool_size,
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
                    "diagnostics": metadata["diagnostics"],
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
    except PolicyTargetNotReachable as exc:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True))
        return 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2, sort_keys=True))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
