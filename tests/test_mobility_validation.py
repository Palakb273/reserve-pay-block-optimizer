from dataclasses import fields
from datetime import datetime
from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.services.mobility_validation import (
    validate_mobility_transaction,
)


def valid_payload() -> dict[str, object]:
    return {
        "transaction_id": "TXN-10001",
        "customer_id": "C1042",
        "estimated_amount_paise": 65000,
        "city": "hyderabad",
        "distance_km": Decimal("18.4"),
        "estimated_duration_minutes": 42,
        "surge_multiplier": Decimal("1.18"),
        "timestamp": "2026-08-23T18:30:00+05:30",
    }


def validation_codes(payload: dict[str, object]) -> dict[str, str]:
    try:
        validate_mobility_transaction(payload)
    except DomainValidationError as exc:
        return {issue.field: issue.code for issue in exc.issues}
    raise AssertionError("Expected payload to fail validation")


class MobilityValidationTests(unittest.TestCase):
    def test_normal_hyderabad_ride_is_normalized(self) -> None:
        result = validate_mobility_transaction(valid_payload())

        self.assertEqual(result["validation_status"], "valid")
        self.assertEqual(result["domain"], "mobility")
        self.assertEqual(result["currency"], "INR")
        transaction = result["transaction"]
        self.assertIsInstance(transaction, dict)
        self.assertEqual(transaction["estimated_amount_paise"], 65000)
        self.assertEqual(transaction["city"], "hyderabad")
        self.assertEqual(transaction["day_of_week"], "sunday")
        self.assertNotIn("actual_amount_paise", transaction)

    def test_valid_surge_ride(self) -> None:
        payload = valid_payload()
        payload["surge_multiplier"] = Decimal("2.25")

        result = validate_mobility_transaction(payload)

        self.assertEqual(result["transaction"]["surge_multiplier"], 2.25)

    def test_zero_distance_and_duration_are_valid(self) -> None:
        payload = valid_payload()
        payload["distance_km"] = Decimal("0")
        payload["estimated_duration_minutes"] = 0

        result = validate_mobility_transaction(payload)

        self.assertEqual(result["transaction"]["distance_km"], 0.0)
        self.assertEqual(result["transaction"]["estimated_duration_minutes"], 0)

    def test_all_supported_cities(self) -> None:
        for city in SupportedCity:
            with self.subTest(city=city.value):
                payload = valid_payload()
                payload["city"] = city.value
                result = validate_mobility_transaction(payload)
                self.assertEqual(result["transaction"]["city"], city.value)

    def test_city_and_timestamp_are_normalized(self) -> None:
        payload = valid_payload()
        payload["city"] = "  HYDERABAD  "
        payload["timestamp"] = "2026-08-23T13:00:00Z"

        result = validate_mobility_transaction(payload)

        self.assertEqual(result["transaction"]["city"], "hyderabad")
        self.assertEqual(
            result["transaction"]["timestamp"], "2026-08-23T18:30:00+05:30"
        )

    def test_zero_or_negative_estimated_amount_is_rejected(self) -> None:
        for amount in (0, -100):
            with self.subTest(amount=amount):
                payload = valid_payload()
                payload["estimated_amount_paise"] = amount
                self.assertEqual(
                    validation_codes(payload)["estimated_amount_paise"],
                    "must_be_positive",
                )

    def test_negative_distance_is_rejected(self) -> None:
        payload = valid_payload()
        payload["distance_km"] = Decimal("-0.1")

        self.assertEqual(
            validation_codes(payload)["distance_km"], "must_be_non_negative"
        )

    def test_negative_duration_is_rejected(self) -> None:
        payload = valid_payload()
        payload["estimated_duration_minutes"] = -1

        self.assertEqual(
            validation_codes(payload)["estimated_duration_minutes"],
            "must_be_non_negative",
        )

    def test_zero_or_negative_surge_is_rejected(self) -> None:
        for surge in (Decimal("0"), Decimal("-0.5")):
            with self.subTest(surge=surge):
                payload = valid_payload()
                payload["surge_multiplier"] = surge
                self.assertEqual(
                    validation_codes(payload)["surge_multiplier"], "must_be_positive"
                )

    def test_unsupported_city_is_rejected(self) -> None:
        payload = valid_payload()
        payload["city"] = "jaipur"

        self.assertEqual(validation_codes(payload)["city"], "unsupported_city")

    def test_empty_transaction_id_is_rejected(self) -> None:
        payload = valid_payload()
        payload["transaction_id"] = "  "

        self.assertEqual(validation_codes(payload)["transaction_id"], "required")

    def test_empty_customer_id_is_rejected(self) -> None:
        payload = valid_payload()
        payload["customer_id"] = ""

        self.assertEqual(validation_codes(payload)["customer_id"], "required")

    def test_money_input_must_be_integer_paise(self) -> None:
        for invalid_amount in (Decimal("650.25"), 650.25, "65000"):
            with self.subTest(amount=invalid_amount):
                payload = valid_payload()
                payload["estimated_amount_paise"] = invalid_amount
                self.assertEqual(
                    validation_codes(payload)["estimated_amount_paise"], "invalid_type"
                )

    def test_timezone_is_required(self) -> None:
        payload = valid_payload()
        payload["timestamp"] = "2026-08-23T18:30:00"

        self.assertEqual(validation_codes(payload)["timestamp"], "timezone_required")

    def test_context_does_not_accept_actual_fare(self) -> None:
        context_fields = {field.name for field in fields(RideTransactionContext)}
        self.assertNotIn("actual_amount", context_fields)
        self.assertNotIn("actual_amount_paise", context_fields)

        payload = valid_payload()
        payload["actual_amount_paise"] = 70000
        self.assertEqual(
            validation_codes(payload)["actual_amount_paise"], "unknown_field"
        )

    def test_actual_fare_belongs_to_separate_outcome(self) -> None:
        outcome = RideTransactionOutcome(
            transaction_id="TXN-10001",
            actual_amount=Money(amount_paise=70250),
            completed_at=datetime.fromisoformat("2026-08-23T19:25:00+05:30"),
        )

        self.assertEqual(outcome.actual_amount.amount_paise, 70250)

    def test_non_mobility_domain_is_rejected(self) -> None:
        payload = valid_payload()
        payload["domain"] = "food_delivery"

        self.assertEqual(validation_codes(payload)["domain"], "unsupported_domain")

    def test_multiple_invalid_fields_are_reported_together(self) -> None:
        payload = valid_payload()
        payload.update(
            {
                "estimated_amount_paise": -100,
                "distance_km": Decimal("-2.5"),
                "estimated_duration_minutes": -10,
                "surge_multiplier": Decimal("0"),
            }
        )

        codes = validation_codes(payload)

        self.assertEqual(codes["estimated_amount_paise"], "must_be_positive")
        self.assertEqual(codes["distance_km"], "must_be_non_negative")
        self.assertEqual(codes["estimated_duration_minutes"], "must_be_non_negative")
        self.assertEqual(codes["surge_multiplier"], "must_be_positive")


if __name__ == "__main__":
    unittest.main()
