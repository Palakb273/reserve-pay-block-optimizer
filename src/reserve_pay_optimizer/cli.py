"""Dependency-free command-line entry point."""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Sequence, TextIO

from reserve_pay_optimizer.config import MOBILITY_DOMAIN, SUPPORTED_CURRENCY
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.evaluation_input import parse_evaluation_dataset
from reserve_pay_optimizer.services.mobility_validation import (
    validate_mobility_transaction,
)
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy


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
        if args.file:
            with args.file.open("r", encoding="utf-8") as stream:
                payload = _load_payload(stream)
        else:
            payload = _load_payload(sys.stdin)
        if args.command == "validate-mobility":
            result = validate_mobility_transaction(payload)  # type: ignore[arg-type]
        else:
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

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
