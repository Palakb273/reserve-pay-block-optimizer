"""Fair comparison of multiple reserve strategies on one transaction set."""

from collections.abc import Sequence

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.evaluation import BaselineComparison
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.services.evaluation import (
    aggregate_evaluations,
    evaluate_transaction,
)
from reserve_pay_optimizer.strategies.base import ReserveStrategy


def _duplicates(values: Sequence[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def compare_strategies(
    transactions: Sequence[RideTransactionContext],
    outcomes: Sequence[RideTransactionOutcome],
    strategies: Sequence[ReserveStrategy],
) -> BaselineComparison:
    """Apply every strategy to exactly the same matched transaction records."""

    issues: list[ValidationIssue] = []
    if not transactions:
        issues.append(
            ValidationIssue(
                "transactions", "empty_dataset", "At least one transaction is required."
            )
        )
    if not strategies:
        issues.append(
            ValidationIssue(
                "strategies", "empty_strategies", "At least one strategy is required."
            )
        )

    transaction_ids = tuple(transaction.transaction_id for transaction in transactions)
    outcome_ids = tuple(outcome.transaction_id for outcome in outcomes)
    strategy_ids = tuple(strategy.strategy_id for strategy in strategies)
    for duplicate in sorted(_duplicates(transaction_ids)):
        issues.append(
            ValidationIssue(
                "transactions",
                "duplicate_transaction_id",
                f"Duplicate transaction_id: {duplicate}.",
            )
        )
    for duplicate in sorted(_duplicates(outcome_ids)):
        issues.append(
            ValidationIssue(
                "outcomes",
                "duplicate_outcome_id",
                f"Duplicate outcome transaction_id: {duplicate}.",
            )
        )
    for duplicate in sorted(_duplicates(strategy_ids)):
        issues.append(
            ValidationIssue(
                "strategies",
                "duplicate_strategy_id",
                f"Duplicate strategy identifier: {duplicate}.",
            )
        )

    transaction_id_set = set(transaction_ids)
    outcome_id_set = set(outcome_ids)
    for missing in sorted(transaction_id_set - outcome_id_set):
        issues.append(
            ValidationIssue(
                "outcomes",
                "missing_outcome",
                f"Missing outcome for transaction_id: {missing}.",
            )
        )
    for unexpected in sorted(outcome_id_set - transaction_id_set):
        issues.append(
            ValidationIssue(
                "outcomes",
                "unexpected_outcome",
                f"Outcome has no matching transaction_id: {unexpected}.",
            )
        )
    if issues:
        raise DomainValidationError(issues)

    outcomes_by_id = {outcome.transaction_id: outcome for outcome in outcomes}
    metrics = []
    for strategy in strategies:
        evaluations = []
        for transaction in transactions:
            decision = strategy.calculate_block(transaction)
            if decision.strategy != strategy.strategy_id:
                raise DomainValidationError(
                    [
                        ValidationIssue(
                            "decision.strategy",
                            "strategy_id_mismatch",
                            "Decision strategy must match the producing strategy.",
                        )
                    ]
                )
            evaluations.append(
                evaluate_transaction(
                    transaction,
                    decision,
                    outcomes_by_id[transaction.transaction_id],
                )
            )
        metrics.append(aggregate_evaluations(evaluations))

    return BaselineComparison(transaction_ids=transaction_ids, metrics=tuple(metrics))

