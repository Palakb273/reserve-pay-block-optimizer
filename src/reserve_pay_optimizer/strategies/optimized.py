"""Distribution-aware strategy adapter for the existing reserve protocol."""

from typing import Protocol

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.optimization.models import (
    OPTIMIZED_STRATEGY_ID,
    OptimizationResult,
)
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.models import PolicyOptimizationResult
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


class FareDistributionPredictor(Protocol):
    def predict(self, context: RideTransactionContext) -> FareDistributionPrediction:
        ...


class OptimizedReserveStrategy:
    """Predict then optimize while accepting decision-time context only."""

    strategy_version = "1"

    def __init__(
        self,
        predictor: FareDistributionPredictor,
        optimizer: ReserveBlockOptimizer | None = None,
        risk_policy: ReserveRiskPolicy | None = None,
    ) -> None:
        self.predictor = predictor
        self.optimizer = optimizer or ReserveBlockOptimizer()
        self.risk_policy = risk_policy
        self.policy_optimizer = PolicyConstrainedOptimizer(self.optimizer)
        self._results: dict[str, OptimizationResult | PolicyOptimizationResult] = {}

    @property
    def strategy_id(self) -> str:
        if self.risk_policy is None:
            return OPTIMIZED_STRATEGY_ID
        return f"optimized_{self.risk_policy.profile.value}"

    @property
    def optimization_results(
        self,
    ) -> tuple[OptimizationResult | PolicyOptimizationResult, ...]:
        return tuple(self._results.values())

    def calculate_block(self, transaction: RideTransactionContext) -> ReserveDecision:
        prediction = self.predictor.predict(transaction)
        if self.risk_policy is None:
            result: OptimizationResult | PolicyOptimizationResult = self.optimizer.optimize(
                transaction, prediction
            )
        else:
            result = self.policy_optimizer.optimize(
                transaction, prediction, self.risk_policy
            )
        self._results[transaction.transaction_id] = result
        return result.reserve_decision
