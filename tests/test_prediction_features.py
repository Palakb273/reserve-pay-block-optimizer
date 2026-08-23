from datetime import datetime
from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.prediction.features import (
    FEATURE_NAMES,
    FORBIDDEN_FEATURE_NAMES,
    PredictionFeatureExtractor,
)


class PredictionFeatureTests(unittest.TestCase):
    def context(self, city: SupportedCity = SupportedCity.HYDERABAD) -> RideTransactionContext:
        return RideTransactionContext(
            transaction_id="SECRET-TXN",
            customer_id="SECRET-CUSTOMER",
            estimated_amount=Money(65000),
            city=city,
            distance_km=Decimal("18.4"),
            estimated_duration_minutes=42,
            surge_multiplier=Decimal("1.18"),
            timestamp=datetime.fromisoformat("2026-08-23T18:30:00+05:30"),
        )

    def test_schema_explicitly_excludes_ids_outcomes_and_simulator_latents(self) -> None:
        forbidden = {
            "transaction_id", "customer_id", "actual_amount_paise", "completed_at",
            "route_change", "traffic_change", "pricing_noise", "actual_distance", "actual_duration",
        }
        self.assertTrue(forbidden.issubset(FORBIDDEN_FEATURE_NAMES))
        self.assertTrue(forbidden.isdisjoint(FEATURE_NAMES))

    def test_numeric_and_timestamp_features_are_correct_and_deterministic(self) -> None:
        extractor = PredictionFeatureExtractor()
        first = extractor.as_mapping(self.context())
        second = extractor.as_mapping(self.context())
        self.assertEqual(first, second)
        self.assertEqual(first["estimated_amount_paise"], 65000.0)
        self.assertEqual(first["distance_km"], 18.4)
        self.assertEqual(first["estimated_duration_minutes"], 42.0)
        self.assertEqual(first["surge_multiplier"], 1.18)
        self.assertEqual(first["day_of_week"], 6.0)
        self.assertEqual(first["is_weekend"], 1.0)
        self.assertAlmostEqual(first["hour_sin"] ** 2 + first["hour_cos"] ** 2, 1.0)

    def test_exactly_one_supported_city_feature_is_active(self) -> None:
        extractor = PredictionFeatureExtractor()
        for city in SupportedCity:
            features = extractor.as_mapping(self.context(city))
            city_values = {name: value for name, value in features.items() if name.startswith("city_")}
            self.assertEqual(sum(city_values.values()), 1.0)
            self.assertEqual(city_values[f"city_{city.value}"], 1.0)


if __name__ == "__main__":
    unittest.main()
