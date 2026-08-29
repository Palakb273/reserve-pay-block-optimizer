"""Reuse Phase-2 metrics for exact, fixed-buffer, and optimized strategies."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from collections.abc import Sequence

from reserve_pay_optimizer.domain.evaluation import BaselineComparison, format_ratio
from reserve_pay_optimizer.domain.mobility import RideTransactionContext, RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from reserve_pay_optimizer.strategies.optimized import FareDistributionPredictor, OptimizedReserveStrategy


@dataclass(frozen=True, slots=True)
class OptimizerEvaluation:
    comparison: BaselineComparison
    optimizer_config: OptimizationConfig
    model_version: str
    average_recommended_block: Money
    average_estimated_collection_probability: Decimal
    average_expected_excess: Money
    average_objective_score: Decimal

    def to_dict(self) -> dict[str, object]:
        value = self.comparison.to_dict()
        value.update(
            {
                "optimizer_configuration": self.optimizer_config.to_dict(),
                "optimizer_diagnostics": {
                    "model_version": self.model_version,
                    "average_recommended_block_paise": self.average_recommended_block.amount_paise,
                    "average_estimated_collection_probability": format_ratio(
                        self.average_estimated_collection_probability
                    ),
                    "average_expected_excess_block_paise": self.average_expected_excess.amount_paise,
                    "average_objective_score": format_ratio(self.average_objective_score),
                },
            }
        )
        return value


def _average_paise(values: Sequence[int]) -> Money:
    rounded = int(
        (Decimal(sum(values)) / Decimal(len(values))).to_integral_value(rounding=ROUND_HALF_UP)
    )
    return Money.from_non_negative_paise(rounded)


def evaluate_optimizer_strategies(
    transactions: Sequence[RideTransactionContext],
    outcomes: Sequence[RideTransactionOutcome],
    predictor: FareDistributionPredictor,
    optimizer: ReserveBlockOptimizer | None = None,
) -> OptimizerEvaluation:
    resolved_optimizer = optimizer or ReserveBlockOptimizer()
    optimized = OptimizedReserveStrategy(predictor, resolved_optimizer)
    comparison = compare_strategies(
        transactions,
        outcomes,
        (ExactEstimateStrategy(), FixedBufferStrategy(), optimized),
    )
    results = optimized.optimization_results
    if not results:
        raise ValueError("optimizer evaluation requires at least one result")
    count = Decimal(len(results))
    return OptimizerEvaluation(
        comparison=comparison,
        optimizer_config=resolved_optimizer.config,
        model_version=results[0].model_version,
        average_recommended_block=_average_paise(
            [result.recommended_block.amount_paise for result in results]
        ),
        average_estimated_collection_probability=sum(
            (result.estimated_collection_probability for result in results), Decimal(0)
        ) / count,
        average_expected_excess=_average_paise(
            [result.expected_excess_block.amount_paise for result in results]
        ),
        average_objective_score=sum(
            (result.objective_score for result in results), Decimal(0)
        ) / count,
    )
