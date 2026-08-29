"""Reserve Pay Block Optimizer package."""

__version__ = "0.5.0"

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
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.models import OptimizationResult
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.prediction.config import MODEL_VERSION, ModelConfig
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel
from reserve_pay_optimizer.services.mobility_validation import (
    validate_mobility_transaction,
)
from reserve_pay_optimizer.simulation.config import FareModelConfig, SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions
from reserve_pay_optimizer.simulation.models import (
    SimulationDataset,
    SimulationDiagnostics,
    SimulationRecord,
)
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from reserve_pay_optimizer.strategies.optimized import OptimizedReserveStrategy

__all__ = [
    "BaselineComparison",
    "Currency",
    "ConditionalFareDistributionModel",
    "DomainValidationError",
    "ExactEstimateStrategy",
    "FareModelConfig",
    "FareDistributionPrediction",
    "FixedBufferStrategy",
    "Money",
    "MODEL_VERSION",
    "ModelConfig",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizedReserveStrategy",
    "ReserveBlockOptimizer",
    "RideTransactionContext",
    "RideTransactionOutcome",
    "ReserveDecision",
    "SimulationConfig",
    "SimulationDataset",
    "SimulationDiagnostics",
    "SimulationRecord",
    "StrategyMetrics",
    "SupportedCity",
    "TransactionDomain",
    "TransactionEvaluation",
    "ValidationIssue",
    "simulate_transactions",
    "validate_mobility_transaction",
    "__version__",
]
