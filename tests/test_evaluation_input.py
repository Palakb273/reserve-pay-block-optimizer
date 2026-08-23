from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.evaluation_input import parse_evaluation_dataset
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy


def dataset_payload() -> dict[str, object]:
    return {
        "records": [
            {
                "transaction": {
                    "transaction_id": "TXN-001",
                    "customer_id": "C001",
                    "estimated_amount_paise": 65000,
                    "city": "hyderabad",
                    "distance_km": Decimal("18.4"),
                    "estimated_duration_minutes": 42,
                    "surge_multiplier": Decimal("1.18"),
                    "timestamp": "2026-08-23T18:30:00+05:30",
                },
                "outcome": {
                    "transaction_id": "TXN-001",
                    "actual_amount_paise": 71000,
                    "completed_at": "2026-08-23T19:20:00+05:30",
                },
            }
        ]
    }


class EvaluationInputTests(unittest.TestCase):
    def test_transaction_and_outcome_are_parsed_as_separate_models(self) -> None:
        transactions, outcomes = parse_evaluation_dataset(dataset_payload())

        self.assertEqual(transactions[0].estimated_amount.amount_paise, 65000)
        self.assertFalse(hasattr(transactions[0], "actual_amount"))
        self.assertEqual(outcomes[0].actual_amount.amount_paise, 71000)

    def test_actual_amount_in_transaction_is_rejected_as_leakage(self) -> None:
        payload = dataset_payload()
        payload["records"][0]["transaction"]["actual_amount_paise"] = 71000  # type: ignore[index]

        with self.assertRaises(DomainValidationError) as caught:
            parse_evaluation_dataset(payload)

        self.assertIn(
            "records[0].transaction.actual_amount_paise",
            {issue.field for issue in caught.exception.issues},
        )

    def test_mismatched_record_ids_are_rejected_before_evaluation(self) -> None:
        payload = dataset_payload()
        payload["records"][0]["outcome"]["transaction_id"] = "TXN-OTHER"  # type: ignore[index]
        transactions, outcomes = parse_evaluation_dataset(payload)

        with self.assertRaises(DomainValidationError) as caught:
            compare_strategies(transactions, outcomes, (ExactEstimateStrategy(),))

        codes = {issue.code for issue in caught.exception.issues}
        self.assertEqual(codes, {"missing_outcome", "unexpected_outcome"})


if __name__ == "__main__":
    unittest.main()
