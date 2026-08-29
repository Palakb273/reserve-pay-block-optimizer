"""Deterministic CDF interpolation and expected-excess integration."""

from decimal import Decimal

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


class QuantileDistribution:
    """A bounded distribution utility over published Q05-through-Q99 values."""

    def __init__(self, prediction: FareDistributionPrediction) -> None:
        if not prediction.quantiles:
            raise ValueError("prediction must contain quantiles")
        self.prediction = prediction
        self.quantile_points = tuple(
            (probability, Decimal(amount.amount_paise))
            for probability, amount in prediction.quantiles
        )
        grouped: dict[int, Decimal] = {}
        for probability, amount in prediction.quantiles:
            grouped[amount.amount_paise] = max(grouped.get(amount.amount_paise, Decimal(0)), probability)
        self.cdf_points = tuple(
            (Decimal(amount), probability) for amount, probability in sorted(grouped.items())
        )

    @property
    def highest_modeled_probability(self) -> Decimal:
        return self.quantile_points[-1][0]

    @property
    def highest_modeled_amount(self) -> Money:
        return Money(amount_paise=int(self.quantile_points[-1][1]))

    def estimated_cdf(self, block: Money | int) -> Decimal:
        """Interpolate between modeled points and cap at the highest quantile."""

        amount = block.amount_paise if isinstance(block, Money) else block
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("block must be a positive integer paise amount or Money")
        block_decimal = Decimal(amount)
        first_amount, first_probability = self.cdf_points[0]
        if block_decimal < first_amount:
            return Decimal(0)
        if block_decimal == first_amount:
            return first_probability
        for (lower_amount, lower_probability), (upper_amount, upper_probability) in zip(
            self.cdf_points, self.cdf_points[1:]
        ):
            if block_decimal <= upper_amount:
                fraction = (block_decimal - lower_amount) / (upper_amount - lower_amount)
                return lower_probability + fraction * (upper_probability - lower_probability)
        return self.highest_modeled_probability

    def _integration_points(self) -> tuple[tuple[Decimal, Decimal], ...]:
        q05, amount05 = self.quantile_points[0]
        q10, amount10 = self.quantile_points[1]
        slope = (amount10 - amount05) / (q10 - q05)
        extrapolated_zero = max(Decimal(1), amount05 - slope * q05)
        return ((Decimal(0), extrapolated_zero), *self.quantile_points)

    def expected_excess_paise(self, block: Money | int) -> Decimal:
        """Analytically integrate max(block-Q(u), 0) over the modeled q=0..Q99 range."""

        amount = block.amount_paise if isinstance(block, Money) else block
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("block must be a positive integer paise amount or Money")
        block_decimal = Decimal(amount)
        total = Decimal(0)
        points = self._integration_points()
        for (lower_q, lower_amount), (upper_q, upper_amount) in zip(points, points[1:]):
            probability_width = upper_q - lower_q
            amount_width = upper_amount - lower_amount
            if block_decimal < lower_amount:
                continue
            if amount_width == 0 or block_decimal >= upper_amount:
                total += probability_width * (
                    block_decimal - (lower_amount + upper_amount) / Decimal(2)
                )
                continue
            fraction = (block_decimal - lower_amount) / amount_width
            total += probability_width * (
                (block_decimal - lower_amount) * fraction
                - amount_width * fraction * fraction / Decimal(2)
            )
        return max(Decimal(0), total)
