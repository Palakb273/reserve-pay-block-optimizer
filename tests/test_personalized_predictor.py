from decimal import Decimal
import unittest

from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from tests.personalization_fixtures import (
    BASE_TIME,
    context_at,
    history_features,
    scaled_distribution,
)


class _HistoryProvider:
    def __init__(self, features: CustomerHistoryFeatures) -> None:
        self.features = features

    def features_for(self, transaction):
        return self.features


class _BaseModel:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, context):
        self.calls += 1
        return scaled_distribution(context, Decimal(1), "base_fixture")


class _BehavioralModel:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, context, history):
        self.calls += 1
        # Uses only observed aggregate behavior, never customer identity.
        scale = history.mean_fare_ratio + history.fare_ratio_stddev
        return scaled_distribution(context, scale, "personalized_fixture")


class PersonalizedPredictorTests(unittest.TestCase):
    def test_cold_start_threshold_routes_zero_one_two_to_base_and_three_to_personalized(self) -> None:
        context = context_at("CURRENT", "C-A", BASE_TIME)
        for count in (0, 1, 2, 3):
            with self.subTest(count=count):
                base = _BaseModel()
                personalized = _BehavioralModel()
                prediction = PersonalizedFarePredictor(
                    base,
                    personalized,
                    _HistoryProvider(history_features("C-A", count)),
                ).predict(context)
                self.assertEqual(prediction.history_count, count)
                self.assertEqual(
                    prediction.prediction_mode,
                    "base" if count < 3 else "personalized",
                )
                self.assertEqual(base.calls, int(count < 3))
                self.assertEqual(personalized.calls, int(count >= 3))

    def test_same_ride_observed_history_changes_balanced_recommendation_without_id_logic(self) -> None:
        stable_context = context_at("CURRENT-A", "C-STABLE", BASE_TIME)
        overrun_context = context_at("CURRENT-B", "C-OVERRUN", BASE_TIME)
        stable = PersonalizedFarePredictor(
            _BaseModel(),
            _BehavioralModel(),
            _HistoryProvider(
                history_features("C-STABLE", 8, "1.00", "0.01", "0.40", "0.02")
            ),
        ).predict(stable_context)
        overrun = PersonalizedFarePredictor(
            _BaseModel(),
            _BehavioralModel(),
            _HistoryProvider(
                history_features("C-OVERRUN", 8, "1.10", "0.08", "0.80", "0.12")
            ),
        ).predict(overrun_context)
        optimizer = PolicyConstrainedOptimizer()
        balanced = ReserveRiskPolicy.for_profile(RiskProfile.BALANCED)
        stable_result = optimizer.optimize(stable_context, stable, balanced)
        overrun_result = optimizer.optimize(overrun_context, overrun, balanced)
        self.assertGreater(
            overrun.amount_for_quantile("0.97").amount_paise,
            stable.amount_for_quantile("0.97").amount_paise,
        )
        self.assertGreater(
            overrun_result.recommended_block.amount_paise,
            stable_result.recommended_block.amount_paise,
        )

    def test_personalized_distribution_works_with_every_existing_policy(self) -> None:
        context = context_at("CURRENT", "C-A", BASE_TIME)
        prediction = PersonalizedFarePredictor(
            _BaseModel(),
            _BehavioralModel(),
            _HistoryProvider(history_features("C-A", 6, "1.03", "0.04")),
        ).predict(context)
        optimizer = PolicyConstrainedOptimizer()
        for profile in RiskProfile:
            result = optimizer.optimize(
                context, prediction, ReserveRiskPolicy.for_profile(profile)
            )
            self.assertTrue(result.policy_satisfied)


if __name__ == "__main__":
    unittest.main()

