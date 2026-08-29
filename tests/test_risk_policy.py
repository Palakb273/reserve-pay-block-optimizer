from dataclasses import FrozenInstanceError
from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.policy.risk import (
    DEFAULT_RISK_PROFILE,
    MAXIMUM_MODELED_PROBABILITY,
    PROFILE_TARGETS,
    ReserveRiskPolicy,
    RiskProfile,
)


class RiskPolicyTests(unittest.TestCase):
    def test_centralized_profile_targets_are_exact(self) -> None:
        self.assertEqual(PROFILE_TARGETS[RiskProfile.CONSERVATIVE], Decimal("0.99"))
        self.assertEqual(PROFILE_TARGETS[RiskProfile.BALANCED], Decimal("0.97"))
        self.assertEqual(PROFILE_TARGETS[RiskProfile.AGGRESSIVE], Decimal("0.93"))
        self.assertEqual(MAXIMUM_MODELED_PROBABILITY, Decimal("0.99"))
        self.assertIs(DEFAULT_RISK_PROFILE, RiskProfile.BALANCED)

    def test_mapping_and_policy_are_immutable(self) -> None:
        with self.assertRaises(TypeError):
            PROFILE_TARGETS[RiskProfile.BALANCED] = Decimal("0.50")  # type: ignore[index]
        policy = ReserveRiskPolicy.for_profile(RiskProfile.BALANCED)
        with self.assertRaises(FrozenInstanceError):
            policy.target_collection_probability = Decimal("0.50")  # type: ignore[misc]

    def test_policy_rejects_non_positive_above_support_and_profile_mismatch(self) -> None:
        for target in (Decimal(0), Decimal("-0.1"), Decimal("1.0"), Decimal("0.96")):
            with self.subTest(target=target), self.assertRaises(DomainValidationError):
                ReserveRiskPolicy(RiskProfile.BALANCED, target)

    def test_default_policy_is_balanced(self) -> None:
        policy = ReserveRiskPolicy.default()
        self.assertIs(policy.profile, RiskProfile.BALANCED)
        self.assertEqual(policy.target_collection_probability, Decimal("0.97"))


if __name__ == "__main__":
    unittest.main()
