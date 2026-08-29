from decimal import Decimal
import unittest

from reserve_pay_optimizer.optimization.distribution import QuantileDistribution
from tests.optimization_fixtures import distribution_prediction


class QuantileDistributionTests(unittest.TestCase):
    def test_exact_lookup_interpolation_and_monotonic_cdf(self) -> None:
        prediction = distribution_prediction()
        distribution = QuantileDistribution(prediction)
        self.assertEqual(prediction.amount_for_quantile("0.50").amount_paise, 10000)
        self.assertEqual(distribution.estimated_cdf(10000), Decimal("0.50"))
        self.assertEqual(distribution.estimated_cdf(11000), Decimal("0.625"))
        values = [distribution.estimated_cdf(amount) for amount in range(4000, 19001, 100)]
        self.assertEqual(values, sorted(values))

    def test_below_range_and_upper_tail_are_conservative(self) -> None:
        distribution = QuantileDistribution(distribution_prediction())
        self.assertEqual(distribution.estimated_cdf(4999), Decimal(0))
        self.assertEqual(distribution.estimated_cdf(18000), Decimal("0.99"))
        self.assertEqual(distribution.estimated_cdf(999999), Decimal("0.99"))
        self.assertLess(distribution.estimated_cdf(999999), Decimal(1))

    def test_duplicate_quantile_amounts_are_safe(self) -> None:
        prediction = distribution_prediction(
            amounts=(5000, 6000, 7500, 10000, 12000, 14000, 14500, 15000, 15000, 18000)
        )
        distribution = QuantileDistribution(prediction)
        self.assertEqual(distribution.estimated_cdf(15000), Decimal("0.97"))
        self.assertLess(distribution.estimated_cdf(14999), Decimal("0.97"))

    def test_expected_excess_uses_exact_piecewise_linear_integration(self) -> None:
        prediction = distribution_prediction(
            amounts=(200, 300, 600, 1000, 1500, 2000, 2200, 2400, 2600, 3000)
        )
        distribution = QuantileDistribution(prediction)
        self.assertEqual(distribution.expected_excess_paise(100), Decimal(0))
        self.assertEqual(distribution.expected_excess_paise(250), Decimal("5.625"))
        values = [distribution.expected_excess_paise(amount) for amount in (100, 250, 1000, 3000, 4000)]
        self.assertEqual(values, sorted(values))

    def test_constant_distribution_integrates_only_modeled_probability_mass(self) -> None:
        distribution = QuantileDistribution(distribution_prediction(amounts=(1000,) * 10))
        self.assertEqual(distribution.expected_excess_paise(500), Decimal(0))
        self.assertEqual(distribution.expected_excess_paise(1500), Decimal("495.00"))


if __name__ == "__main__":
    unittest.main()
