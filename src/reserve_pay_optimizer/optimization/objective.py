"""Transparent dimensionless reserve-block objective."""

from decimal import Decimal

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.distribution import QuantileDistribution
from reserve_pay_optimizer.optimization.models import CandidateScore, ScoreComponents


def score_candidate(
    transaction: RideTransactionContext,
    distribution: QuantileDistribution,
    block_amount_paise: int,
    config: OptimizationConfig,
) -> CandidateScore:
    block = Money(amount_paise=block_amount_paise)
    estimate = Decimal(transaction.estimated_amount.amount_paise)
    collection_probability = distribution.estimated_cdf(block)
    under_probability = Decimal(1) - collection_probability
    expected_excess_paise = distribution.expected_excess_paise(block)
    expected_excess_ratio = expected_excess_paise / estimate
    friction_ratio = Decimal(
        max(block_amount_paise - transaction.estimated_amount.amount_paise, 0)
    ) / estimate
    components = ScoreComponents(
        under_block_component=config.lambda_under * under_probability,
        excess_component=config.lambda_excess * expected_excess_ratio,
        friction_component=config.lambda_friction * friction_ratio,
    )
    return CandidateScore(
        block_amount=block,
        estimated_collection_probability=collection_probability,
        estimated_under_block_probability=under_probability,
        expected_excess_block_paise_exact=expected_excess_paise,
        expected_excess_block_ratio=expected_excess_ratio,
        friction_ratio=friction_ratio,
        score_components=components,
    )
