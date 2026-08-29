"""Distribution-aware strategy adapter for the existing reserve protocol."""

from typing import Protocol

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.optimization.models import (
    OPTIMIZED_STRATEGY_ID,
    OptimizationResult,
)
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


class FareDistributionPredictor(Protocol):
    def predict(self, context: RideTransactionContext) -> FareDistributionPrediction:
        ...


class OptimizedReserveStrategy:
    """Predict then optimize while accepting decision-time context only."""

    strategy_id = OPTIMIZED_STRATEGY_ID
    strategy_version = "1"

    def __init__(
        self,
        predictor: FareDistributionPredictor,
        optimizer: ReserveBlockOptimizer | None = None,
    ) -> None:
        self.predictor = predictor
        self.optimizer = optimizer or ReserveBlockOptimizer()
        self._results: dict[str, OptimizationResult] = {}

    @property
    def optimization_results(self) -> tuple[OptimizationResult, ...]:
        return tuple(self._results.values())

    def calculate_block(self, transaction: RideTransactionContext) -> ReserveDecision:
        prediction = self.predictor.predict(transaction)
        result = self.optimizer.optimize(transaction, prediction)
        self._results[transaction.transaction_id] = result
        return result.reserve_decision
