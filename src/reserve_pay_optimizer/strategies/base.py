"""Plug-in boundary shared by baselines and future optimizer strategies."""

from typing import Protocol, runtime_checkable

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.reserve import ReserveDecision


@runtime_checkable
class ReserveStrategy(Protocol):
    """A reserve decision-maker with no access to post-ride outcomes."""

    @property
    def strategy_id(self) -> str:
        ...

    def calculate_block(
        self, transaction: RideTransactionContext
    ) -> ReserveDecision:
        ...

