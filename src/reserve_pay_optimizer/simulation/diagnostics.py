"""Descriptive quality checks for generated simulator records."""

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from reserve_pay_optimizer.config import METRIC_RATIO_QUANTUM
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.simulation.models import (
    SimulationDiagnostics,
    SimulationRecord,
)


def _ratio(numerator: int, denominator: int) -> Decimal:
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        METRIC_RATIO_QUANTUM, rounding=ROUND_HALF_UP
    )


def _average_money(total_paise: int, count: int) -> Money:
    value = int(
        (Decimal(total_paise) / Decimal(count)).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    return Money.from_non_negative_paise(value)


def summarize_simulation(
    records: Sequence[SimulationRecord],
    near_estimate_ratio: Decimal = Decimal("0.02"),
) -> SimulationDiagnostics:
    if not records:
        raise DomainValidationError(
            [
                ValidationIssue(
                    "records",
                    "empty_dataset",
                    "At least one simulation record is required for diagnostics.",
                )
            ]
        )
    count = len(records)
    estimated_values = [
        record.transaction.estimated_amount.amount_paise for record in records
    ]
    actual_values = [record.outcome.actual_amount.amount_paise for record in records]
    differences = [
        actual - estimated
        for estimated, actual in zip(estimated_values, actual_values, strict=True)
    ]
    above = sum(difference > 0 for difference in differences)
    below = sum(difference < 0 for difference in differences)
    equal = sum(difference == 0 for difference in differences)
    near = sum(
        abs(difference)
        <= max(
            1,
            int(
                (Decimal(estimated) * near_estimate_ratio).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            ),
        )
        for estimated, difference in zip(estimated_values, differences, strict=True)
    )
    surge_count = sum(
        record.transaction.surge_multiplier > Decimal(1) for record in records
    )
    city_counts = Counter(record.transaction.city.value for record in records)
    return SimulationDiagnostics(
        transaction_count=count,
        unique_customer_count=len(
            {record.transaction.customer_id for record in records}
        ),
        city_counts=tuple(sorted(city_counts.items())),
        average_estimated_amount=_average_money(sum(estimated_values), count),
        average_actual_amount=_average_money(sum(actual_values), count),
        actual_above_estimate_rate=_ratio(above, count),
        actual_below_estimate_rate=_ratio(below, count),
        actual_equal_estimate_rate=_ratio(equal, count),
        actual_near_estimate_rate=_ratio(near, count),
        average_absolute_difference=_average_money(
            sum(abs(difference) for difference in differences), count
        ),
        surge_frequency=_ratio(surge_count, count),
        near_estimate_ratio=near_estimate_ratio,
    )

