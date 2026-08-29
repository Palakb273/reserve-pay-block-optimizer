from decimal import Decimal
import unittest

from reserve_pay_optimizer.personalization.features import (
    PERSONALIZATION_FORBIDDEN_FEATURE_NAMES,
    PERSONALIZED_FEATURE_NAMES,
    PersonalizedFeatureExtractor,
)
from reserve_pay_optimizer.prediction.features import FEATURE_NAMES
from tests.personalization_fixtures import BASE_TIME, context_at, history_features


class PersonalizedFeatureTests(unittest.TestCase):
    def test_context_and_history_features_are_exact(self) -> None:
        context = context_at("CURRENT", "C-A", BASE_TIME, 12345)
        history = history_features(
            "C-A", 7, "1.04", "0.06", "0.70", "0.08"
        )
        values = PersonalizedFeatureExtractor().as_mapping(context, history)
        self.assertEqual(tuple(values), PERSONALIZED_FEATURE_NAMES)
        self.assertEqual(tuple(values)[: len(FEATURE_NAMES)], FEATURE_NAMES)
        self.assertEqual(values["customer_history_count"], 7.0)
        self.assertEqual(values["customer_mean_fare_ratio"], 1.04)
        self.assertEqual(values["customer_fare_ratio_stddev"], 0.06)
        self.assertEqual(values["customer_overrun_rate"], 0.70)
        self.assertEqual(values["customer_mean_positive_overrun_ratio"], 0.08)

    def test_ids_outcomes_and_hidden_simulator_values_are_forbidden(self) -> None:
        self.assertNotIn("customer_id", PERSONALIZED_FEATURE_NAMES)
        self.assertNotIn("transaction_id", PERSONALIZED_FEATURE_NAMES)
        self.assertTrue(
            {
                "customer_id",
                "transaction_id",
                "actual_amount_paise",
                "completed_at",
                "customer_overrun_bias",
                "customer_variance_multiplier",
            }.issubset(PERSONALIZATION_FORBIDDEN_FEATURE_NAMES)
        )

    def test_history_identity_must_match_but_never_becomes_numeric(self) -> None:
        context = context_at("CURRENT", "C-A", BASE_TIME, 12345)
        with self.assertRaises(ValueError):
            PersonalizedFeatureExtractor().extract(
                context, history_features("C-B", 3)
            )


if __name__ == "__main__":
    unittest.main()

