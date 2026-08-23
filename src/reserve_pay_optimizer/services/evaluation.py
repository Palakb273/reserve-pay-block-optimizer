"""Post-transaction evaluation and aggregation services."""

from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from reserve_pay_optimizer.config import METRIC_RATIO_QUANTUM
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.evaluation import StrategyMetrics, TransactionEvaluation
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision


def _quantized_ratio(numerator: int, denominator: int) -> Decimal:
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        METRIC_RATIO_QUANTUM, rounding=ROUND_HALF_UP
    )


def _average_money(total_paise: int, count: int) -> Money:
    average_paise = int(
        (Decimal(total_paise) / Decimal(count)).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    return Money.from_non_negative_paise(average_paise)


def evaluate_transaction(
    transaction: RideTransactionContext,
    decision: ReserveDecision,
    outcome: RideTransactionOutcome,
) -> TransactionEvaluation:
    """Evaluate a previously made decision using the now-known outcome."""

    issues: list[ValidationIssue] = []
    if decision.transaction_id != transaction.transaction_id:
        issues.append(
            ValidationIssue(
                "decision.transaction_id",
                "transaction_id_mismatch",
                "Decision transaction_id must match the transaction context.",
            )
        )
    if outcome.transaction_id != transaction.transaction_id:
        issues.append(
            ValidationIssue(
                "outcome.transaction_id",
                "transaction_id_mismatch",
                "Outcome transaction_id must match the transaction context.",
            )
        )
    if issues:
        raise DomainValidationError(issues)

    block_paise = decision.block_amount.amount_paise
    actual_paise = outcome.actual_amount.amount_paise
    excess_paise = max(block_paise - actual_paise, 0)
    under_paise = max(actual_paise - block_paise, 0)
    return TransactionEvaluation(
        transaction_id=transaction.transaction_id,
        strategy=decision.strategy,
        estimated_amount=transaction.estimated_amount,
        block_amount=decision.block_amount,
        actual_amount=outcome.actual_amount,
        excess_block=Money.from_non_negative_paise(excess_paise),
        under_block=Money.from_non_negative_paise(under_paise),
    )


def aggregate_evaluations(
    evaluations: Sequence[TransactionEvaluation],
) -> StrategyMetrics:
    """Aggregate one strategy's evaluations with deterministic precision."""

    if not evaluations:
        raise DomainValidationError(
            [
                ValidationIssue(
                    "evaluations",
                    "empty_dataset",
                    "At least one transaction evaluation is required.",
                )
            ]
        )
    strategies = {evaluation.strategy for evaluation in evaluations}
    if len(strategies) != 1:
        raise DomainValidationError(
            [
                ValidationIssue(
                    "evaluations.strategy",
                    "mixed_strategies",
                    "Aggregate metrics require evaluations from exactly one strategy.",
                )
            ]
        )

    count = len(evaluations)
    success_count = sum(evaluation.collection_success for evaluation in evaluations)
    under_count = sum(evaluation.is_under_blocked for evaluation in evaluations)
    total_excess = sum(
        evaluation.excess_block.amount_paise for evaluation in evaluations
    )
    total_under = sum(
        evaluation.under_block.amount_paise for evaluation in evaluations
    )
    total_blocked = sum(
        evaluation.block_amount.amount_paise for evaluation in evaluations
    )
    total_actual = sum(
        evaluation.actual_amount.amount_paise for evaluation in evaluations
    )
    collectible_reserved = sum(
        min(
            evaluation.block_amount.amount_paise,
            evaluation.actual_amount.amount_paise,
        )
        for evaluation in evaluations
    )
    excess_ratio_sum = sum(
        (evaluation.excess_block_ratio for evaluation in evaluations),
        start=Decimal(0),
    )

    return StrategyMetrics(
        strategy=strategies.pop(),
        transaction_count=count,
        collection_success_count=success_count,
        collection_success_rate=_quantized_ratio(success_count, count),
        under_block_count=under_count,
        under_block_rate=_quantized_ratio(under_count, count),
        average_excess_block=_average_money(total_excess, count),
        average_under_block=_average_money(total_under, count),
        total_blocked_amount=Money(amount_paise=total_blocked),
        total_actual_amount=Money(amount_paise=total_actual),
        capital_efficiency=_quantized_ratio(collectible_reserved, total_blocked),
        average_excess_block_ratio=(
            excess_ratio_sum / Decimal(count)
        ).quantize(METRIC_RATIO_QUANTUM, rounding=ROUND_HALF_UP),
    )

