from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal
import unittest

from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY
from reserve_pay_optimizer.personalization.dataset import build_personalized_records
from reserve_pay_optimizer.personalization.persistence import (
    load_personalized_artifact,
    save_personalized_artifact,
)
from reserve_pay_optimizer.personalization.training import train_personalized_predictor
from reserve_pay_optimizer.prediction.config import QUANTILES, ModelConfig, quantile_key
from reserve_pay_optimizer.prediction.persistence import load_predictor_artifact
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class PersonalizedTrainingTests(unittest.TestCase):
    def test_small_chronological_training_persistence_and_monotonic_prediction(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(
                transaction_count=120,
                seed=709,
                customer_pool_size=8,
                customer_behavior_enabled=True,
            )
        )
        base = load_predictor_artifact(
            Path("artifacts/prediction/fare_distribution_v1")
        ).model
        config = ModelConfig(
            seed=9,
            n_estimators=5,
            learning_rate=0.05,
            max_depth=2,
            min_samples_leaf=2,
        )
        training = train_personalized_predictor(
            dataset.transactions, dataset.outcomes, base, config
        )
        self.assertEqual(
            set(training.model.quantile_models),
            {quantile_key(value) for value in QUANTILES},
        )
        self.assertGreater(training.personalized_training_record_count, 0)
        eligible = next(
            record
            for record in training.split.test
            if record.history.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
        )
        prediction = training.model.predict(eligible.context, eligible.history)
        amounts = [money.amount_paise for _, money in prediction.quantiles]
        self.assertEqual(amounts, sorted(amounts))
        with TemporaryDirectory() as temporary:
            artifact_path = Path(temporary) / "personalized"
            save_personalized_artifact(training, artifact_path)
            loaded = load_personalized_artifact(artifact_path)
            reloaded = loaded.model.predict(eligible.context, eligible.history)
        self.assertEqual(prediction.to_dict(), reloaded.to_dict())
        self.assertEqual(
            loaded.metadata["minimum_personalization_history"], 3
        )

    def test_each_record_target_remains_fare_ratio(self) -> None:
        dataset = simulate_transactions(
            SimulationConfig(
                transaction_count=20,
                seed=710,
                customer_pool_size=3,
                customer_behavior_enabled=True,
            )
        )
        records = build_personalized_records(dataset.transactions, dataset.outcomes)
        for record in records:
            self.assertEqual(
                record.fare_ratio,
                Decimal(record.outcome.actual_amount.amount_paise)
                / Decimal(record.context.estimated_amount.amount_paise),
            )


if __name__ == "__main__":
    unittest.main()
