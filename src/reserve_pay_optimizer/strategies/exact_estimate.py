"""Exact-estimate reserve baseline."""

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.reserve import ReserveDecision


class ExactEstimateStrategy:
    strategy_id = "exact_estimate"
    strategy_version = "1"

    def calculate_block(
        self, transaction: RideTransactionContext
    ) -> ReserveDecision:
        return ReserveDecision(
            transaction_id=transaction.transaction_id,
            strategy=self.strategy_id,
            strategy_version=self.strategy_version,
            block_amount=transaction.estimated_amount,
        )

