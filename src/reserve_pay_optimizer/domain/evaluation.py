"""Typed transaction and aggregate baseline evaluation results."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from reserve_pay_optimizer.config import METRIC_RATIO_QUANTUM
from reserve_pay_optimizer.domain.money import Money


def format_ratio(value: Decimal) -> str:
    """Serialize a ratio deterministically as a six-place decimal string."""

    return format(
        value.quantize(METRIC_RATIO_QUANTUM, rounding=ROUND_HALF_UP), "f"
    )


@dataclass(frozen=True, slots=True)
class TransactionEvaluation:
    transaction_id: str
    strategy: str
    estimated_amount: Money
    block_amount: Money
    actual_amount: Money
    excess_block: Money
    under_block: Money

    @property
    def collection_success(self) -> bool:
        return self.block_amount.amount_paise >= self.actual_amount.amount_paise

    @property
    def is_under_blocked(self) -> bool:
        return self.under_block.amount_paise > 0

    @property
    def excess_block_ratio(self) -> Decimal:
        return Decimal(self.excess_block.amount_paise) / Decimal(
            self.block_amount.amount_paise
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "strategy": self.strategy,
            "estimated_amount_paise": self.estimated_amount.amount_paise,
            "block_amount_paise": self.block_amount.amount_paise,
            "actual_amount_paise": self.actual_amount.amount_paise,
            "collection_success": self.collection_success,
            "excess_block_paise": self.excess_block.amount_paise,
            "under_block_paise": self.under_block.amount_paise,
            "is_under_blocked": self.is_under_blocked,
            "excess_block_ratio": format_ratio(self.excess_block_ratio),
        }


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    strategy: str
    transaction_count: int
    collection_success_count: int
    collection_success_rate: Decimal
    under_block_count: int
    under_block_rate: Decimal
    average_excess_block: Money
    average_under_block: Money
    total_blocked_amount: Money
    total_actual_amount: Money
    capital_efficiency: Decimal
    average_excess_block_ratio: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "transaction_count": self.transaction_count,
            "collection_success_count": self.collection_success_count,
            "collection_success_rate": format_ratio(self.collection_success_rate),
            "under_block_count": self.under_block_count,
            "under_block_rate": format_ratio(self.under_block_rate),
            "average_excess_block_paise": self.average_excess_block.amount_paise,
            "average_under_block_paise": self.average_under_block.amount_paise,
            "total_blocked_amount_paise": self.total_blocked_amount.amount_paise,
            "total_actual_amount_paise": self.total_actual_amount.amount_paise,
            "capital_efficiency": format_ratio(self.capital_efficiency),
            "average_excess_block_ratio": format_ratio(
                self.average_excess_block_ratio
            ),
        }


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    transaction_ids: tuple[str, ...]
    metrics: tuple[StrategyMetrics, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "comparison_status": "complete",
            "transaction_ids": list(self.transaction_ids),
            "strategies": {
                metric.strategy: metric.to_dict() for metric in self.metrics
            },
        }
