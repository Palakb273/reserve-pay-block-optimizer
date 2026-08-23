from datetime import datetime
from decimal import Decimal
import unittest

from reserve_pay_optimizer.config import INDIA_STANDARD_TIME
from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.simulation.config import FareModelConfig, SimulationConfig
from reserve_pay_optimizer.simulation.profiles import CitySimulationProfile


class SimulationConfigTests(unittest.TestCase):
    def test_rejects_non_positive_count_and_customer_pool(self) -> None:
        for kwargs in ({"transaction_count": 0}, {"customer_pool_size": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(DomainValidationError):
                SimulationConfig(**kwargs)

    def test_rejects_end_before_start(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            SimulationConfig(
                start_datetime=datetime(2026, 2, 1, tzinfo=INDIA_STANDARD_TIME),
                end_datetime=datetime(2026, 1, 1, tzinfo=INDIA_STANDARD_TIME),
            )

        self.assertIn("invalid_range", {issue.code for issue in caught.exception.issues})

    def test_rejects_naive_timestamps(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            SimulationConfig(start_datetime=datetime(2026, 1, 1))

        self.assertIn(
            "timezone_required", {issue.code for issue in caught.exception.issues}
        )

    def test_rejects_invalid_city_weights(self) -> None:
        invalid_weights = (
            (),
            ((SupportedCity.DELHI, 0),),
            ((SupportedCity.DELHI, 1), (SupportedCity.DELHI, 2)),
        )
        for weights in invalid_weights:
            with self.subTest(weights=weights), self.assertRaises(DomainValidationError):
                SimulationConfig(city_weights=weights)

    def test_weighted_city_requires_a_profile(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            SimulationConfig(
                city_weights=((SupportedCity.MUMBAI, 1),),
                city_profiles=(
                    CitySimulationProfile(
                        SupportedCity.DELHI,
                        Decimal("10"),
                        Decimal("5"),
                        Decimal("25"),
                        Decimal("0.1"),
                        Decimal("0.05"),
                        Decimal("0.1"),
                    ),
                ),
            )

        self.assertIn("missing_profile", {issue.code for issue in caught.exception.issues})

    def test_profile_rejects_invalid_probability(self) -> None:
        with self.assertRaises(DomainValidationError):
            CitySimulationProfile(
                SupportedCity.DELHI,
                Decimal("10"),
                Decimal("5"),
                Decimal("25"),
                Decimal("1.1"),
                Decimal("0.05"),
                Decimal("0.1"),
            )

    def test_fare_model_rejects_invalid_ranges(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            FareModelConfig(
                minimum_distance_km=Decimal("10"),
                maximum_distance_km=Decimal("5"),
            )

        self.assertIn("invalid_range", {issue.code for issue in caught.exception.issues})

    def test_fare_model_rejects_unusable_surge_interval(self) -> None:
        with self.assertRaises(DomainValidationError):
            FareModelConfig(maximum_surge_multiplier=Decimal("1.02"))


if __name__ == "__main__":
    unittest.main()
