from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.prediction.persistence import (
    load_predictor_artifact,
    validate_artifact_compatibility,
)
from reserve_pay_optimizer.services.comparison import compare_strategies
from reserve_pay_optimizer.services.optimizer_evaluation import evaluate_optimizer_strategies
from reserve_pay_optimizer.strategies.base import ReserveStrategy
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from reserve_pay_optimizer.strategies.optimized import OptimizedReserveStrategy
from tests.fixtures import make_context, make_outcome
from tests.optimization_fixtures import distribution_prediction


class FixturePredictor:
    def predict(self, context):
        return distribution_prediction(context.transaction_id)


class OptimizedStrategyTests(unittest.TestCase):
    def test_existing_protocol_and_comparison_service_accept_strategy(self) -> None:
        strategy = OptimizedReserveStrategy(FixturePredictor())
        self.assertIsInstance(strategy, ReserveStrategy)
        contexts = (make_context("A", 10000), make_context("B", 10000))
        outcomes = (make_outcome("A", 11000), make_outcome("B", 15000))
        comparison = compare_strategies(
            contexts, outcomes, (ExactEstimateStrategy(), FixedBufferStrategy(), strategy)
        )
        self.assertEqual(
            {metric.strategy for metric in comparison.metrics},
            {"exact_estimate", "fixed_buffer_20", "optimized_reserve"},
        )
        self.assertEqual(len(strategy.optimization_results), 2)

    def test_optimizer_evaluation_adds_decision_time_diagnostics(self) -> None:
        contexts = (make_context("A", 10000), make_context("B", 10000))
        outcomes = (make_outcome("A", 11000), make_outcome("B", 15000))
        evaluation = evaluate_optimizer_strategies(contexts, outcomes, FixturePredictor())
        result = evaluation.to_dict()
        self.assertIn("optimized_reserve", result["strategies"])
        self.assertGreater(result["optimizer_diagnostics"]["average_recommended_block_paise"], 0)
        self.assertNotIn("actual_amount", result["optimizer_diagnostics"])

    def test_real_trusted_artifact_loads_and_optimizes_one_context(self) -> None:
        artifact = load_predictor_artifact(Path("artifacts/prediction/fare_distribution_v1"))
        context = make_context("MODEL-INTEGRATION", 65000)
        result = ReserveBlockOptimizer().optimize(context, artifact.model.predict(context))
        self.assertGreater(result.recommended_block.amount_paise, 0)
        self.assertLessEqual(result.estimated_collection_probability, Decimal("0.99"))

    def test_incompatible_library_metadata_is_rejected(self) -> None:
        metadata = {
            "library_versions": {
                "scikit_learn": "0.0-incompatible",
                "joblib": "0.0-incompatible",
            }
        }
        with self.assertRaisesRegex(ValueError, "incompatible trusted artifact"):
            validate_artifact_compatibility(metadata)

    def test_incompatible_artifact_fails_before_joblib_deserialization(self) -> None:
        metadata = {
            "model_version": "fare_distribution_v1",
            "library_versions": {
                "scikit_learn": "0.0-incompatible",
                "joblib": "0.0-incompatible",
            },
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            with patch("reserve_pay_optimizer.prediction.persistence.joblib.load") as loader:
                with self.assertRaisesRegex(ValueError, "incompatible trusted artifact"):
                    load_predictor_artifact(directory)
                loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
