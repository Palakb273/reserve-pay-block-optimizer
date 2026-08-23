"""Reserve Pay Block Optimizer domain and baseline evaluation package."""

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.evaluation import (
    BaselineComparison,
    StrategyMetrics,
    TransactionEvaluation,
)
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.domain.types import Currency, SupportedCity, TransactionDomain
from reserve_pay_optimizer.services.mobility_validation import (
    validate_mobility_transaction,
)
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy

__all__ = [
    "BaselineComparison",
    "Currency",
    "DomainValidationError",
    "ExactEstimateStrategy",
    "FixedBufferStrategy",
    "Money",
    "RideTransactionContext",
    "RideTransactionOutcome",
    "ReserveDecision",
    "StrategyMetrics",
    "SupportedCity",
    "TransactionDomain",
    "TransactionEvaluation",
    "ValidationIssue",
    "validate_mobility_transaction",
]
