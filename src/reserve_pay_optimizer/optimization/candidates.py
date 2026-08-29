"""Bounded, deterministic reserve-block candidate generation."""

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction
from reserve_pay_optimizer.optimization.config import OptimizationConfig

MAX_REGULAR_CANDIDATES = 10_000


def generate_candidates(
    transaction: RideTransactionContext,
    prediction: FareDistributionPrediction,
    config: OptimizationConfig,
) -> tuple[int, ...]:
    quantile_amounts = {
        amount.amount_paise for _, amount in prediction.quantiles
    }
    estimate = transaction.estimated_amount.amount_paise
    q50 = prediction.amount_for_quantile("0.50").amount_paise
    q99 = prediction.amount_for_quantile("0.99").amount_paise
    lower = min(estimate, q50)
    upper = max(estimate, q99)
    candidates = {estimate, lower, upper, *quantile_amounts}
    step = config.candidate_step_paise
    if (upper - lower) // step > MAX_REGULAR_CANDIDATES:
        raise ValueError(
            "candidate range would exceed 10,000 regular steps; increase candidate_step_paise"
        )
    regular = ((lower + step - 1) // step) * step
    while regular <= upper:
        candidates.add(regular)
        regular += step
    return tuple(sorted(value for value in candidates if 0 < value <= upper))
