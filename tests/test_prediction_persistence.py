import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reserve_pay_optimizer.prediction.config import ModelConfig
from reserve_pay_optimizer.prediction.persistence import (
    load_predictor_artifact,
    save_predictor_artifact,
)
from reserve_pay_optimizer.prediction.training import train_predictor
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class PredictionPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dataset = simulate_transactions(SimulationConfig(transaction_count=120, seed=51, customer_pool_size=30))
        cls.contexts = tuple(record.transaction for record in dataset.records)
        cls.outcomes = tuple(record.outcome for record in dataset.records)
        cls.training = train_predictor(
            cls.contexts,
            cls.outcomes,
            ModelConfig(seed=51, n_estimators=10, min_samples_leaf=3),
        )

    def test_save_reload_preserves_metadata_models_and_prediction(self) -> None:
        with TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "fare_distribution_v1"
            save_predictor_artifact(self.training, artifact)
            expected_files = {
                "metadata.json", "feature_schema.json", "evaluation_summary.json", "baseline_ratios.json", "models"
            }
            self.assertEqual({path.name for path in artifact.iterdir()}, expected_files)
            self.assertEqual(len(tuple((artifact / "models").glob("*.joblib"))), 10)
            loaded = load_predictor_artifact(artifact)
            context = self.training.split.test[0].context
            self.assertEqual(
                self.training.model.predict(context).to_dict(),
                loaded.model.predict(context).to_dict(),
            )
            self.assertEqual(loaded.metadata["dataset_fingerprint_sha256"], self.training.dataset_fingerprint)
            self.assertEqual(loaded.metadata["target_definition"], "fare_ratio=actual_amount_paise/estimated_amount_paise")
            schema = json.loads((artifact / "feature_schema.json").read_text(encoding="utf-8"))
            self.assertIn("customer_id", schema["forbidden_features"])


if __name__ == "__main__":
    unittest.main()
