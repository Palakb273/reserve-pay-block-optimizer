from decimal import Decimal
import unittest

from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.dataset import PredictionRecord
from reserve_pay_optimizer.prediction.distribution import crossing_count, repair_monotonic
from reserve_pay_optimizer.prediction.evaluation import (
    calculate_prediction_metrics,
    pinball_loss,
)
from tests.fixtures import make_context, make_outcome


class PredictionMetricTests(unittest.TestCase):
    def test_pinball_loss_formula_by_side_of_quantile(self) -> None:
        self.assertEqual(pinball_loss(120, 100, Decimal("0.90")), Decimal("18.00"))
        self.assertEqual(pinball_loss(80, 100, Decimal("0.90")), Decimal("2.00"))
        self.assertEqual(pinball_loss(100, 100, Decimal("0.50")), Decimal(0))

    def test_crossing_detection_and_cumulative_max_repair(self) -> None:
        raw = {Decimal("0.05"): 100, Decimal("0.50"): 130, Decimal("0.90"): 120, Decimal("0.99"): 150}
        self.assertEqual(crossing_count(raw), 1)
        repaired = repair_monotonic(raw)
        self.assertEqual(repaired[Decimal("0.90")], 130)
        self.assertEqual(crossing_count(repaired), 0)

    def test_coverage_calibration_interval_and_median_mae_fixture(self) -> None:
        records = (
            PredictionRecord(make_context("A", 100), make_outcome("A", 90)),
            PredictionRecord(make_context("B", 100), make_outcome("B", 110)),
        )

        def predictions(record: PredictionRecord) -> dict[Decimal, int]:
            return {quantile: 100 for quantile in QUANTILES}

        metrics = calculate_prediction_metrics(records, predictions)
        q90 = dict(metrics.quantiles)[Decimal("0.90")]
        self.assertEqual(q90.observed_coverage, Decimal("0.5"))
        self.assertEqual(q90.calibration_error, Decimal("-0.40"))
        self.assertEqual(q90.absolute_calibration_error, Decimal("0.40"))
        self.assertEqual(metrics.median_mae_paise, Decimal(10))
        self.assertEqual(metrics.interval_05_95_coverage, Decimal(0))
        self.assertEqual(metrics.interval_05_95_average_width_paise, Decimal(0))


if __name__ == "__main__":
    unittest.main()
