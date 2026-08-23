from decimal import Decimal
import unittest

from reserve_pay_optimizer.config import MAX_AMOUNT_PAISE
from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.domain.money import Money


class MoneyTests(unittest.TestCase):
    def test_integer_paise_round_trips_to_exact_decimal_rupees(self) -> None:
        money = Money(amount_paise=65000)

        self.assertEqual(money.amount_paise, 65000)
        self.assertEqual(money.amount_rupees, Decimal("650"))
        self.assertEqual(money.to_dict(), {"amount_paise": 65000, "currency": "INR"})

    def test_decimal_rupees_convert_exactly_to_paise(self) -> None:
        self.assertEqual(Money.from_rupees(Decimal("650.25")).amount_paise, 65025)

    def test_rupee_amount_rejects_sub_paise_precision(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            Money.from_rupees(Decimal("650.001"))

        self.assertEqual(caught.exception.issues[0].code, "invalid_precision")

    def test_rupee_amount_rejects_binary_float(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            Money.from_rupees(650.25)  # type: ignore[arg-type]

        self.assertEqual(caught.exception.issues[0].code, "invalid_type")

    def test_amount_must_be_positive(self) -> None:
        for amount in (0, -1):
            with self.subTest(amount=amount), self.assertRaises(DomainValidationError):
                Money(amount_paise=amount)

    def test_amount_must_fit_signed_64_bit_paise_range(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            Money(amount_paise=MAX_AMOUNT_PAISE + 1)

        self.assertEqual(caught.exception.issues[0].code, "out_of_range")

    def test_evaluation_delta_factory_allows_exact_zero(self) -> None:
        money = Money.from_non_negative_paise(0)

        self.assertEqual(money.amount_paise, 0)

    def test_evaluation_delta_factory_still_rejects_negative_values(self) -> None:
        with self.assertRaises(DomainValidationError) as caught:
            Money.from_non_negative_paise(-1)

        self.assertEqual(caught.exception.issues[0].code, "must_be_non_negative")


if __name__ == "__main__":
    unittest.main()
