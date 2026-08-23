from decimal import Decimal
import unittest

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.prediction.config import QUANTILES, ModelConfig, quantile_key
from reserve_pay_optimizer.prediction.dataset import build_prediction_records, split_records
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class PredictionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dataset = simulate_transactions(SimulationConfig(transaction_count=140, seed=42, customer_pool_size=20))
        records = build_prediction_records(
            tuple(record.transaction for record in dataset.records),
            tuple(record.outcome for record in dataset.records),
        )
        cls.split = split_records(records, ModelConfig(seed=42, n_estimators=12, min_samples_leaf=3))

    def test_trains_every_quantile_and_predicts_monotonic_money(self) -> None:
        model = ConditionalFareDistributionModel(ModelConfig(seed=42, n_estimators=12, min_samples_leaf=3)).fit(self.split.train)
        self.assertEqual(set(model.quantile_models), {quantile_key(value) for value in QUANTILES})
        prediction = model.predict(self.split.test[0].context)
        self.assertEqual(prediction.transaction_id, self.split.test[0].context.transaction_id)
        self.assertFalse(hasattr(prediction, "customer_id"))
        amounts = [amount.amount_paise for _, amount in prediction.quantiles]
        self.assertTrue(all(isinstance(amount, Money) for _, amount in prediction.quantiles))
        self.assertEqual(amounts, sorted(amounts))
        self.assertIs(prediction.amount_for_quantile(Decimal("0.97")), dict(prediction.quantiles)[Decimal("0.97")])
        with self.assertRaises(KeyError):
            prediction.amount_for_quantile("1.00")

    def test_same_seed_data_and_config_produce_equivalent_predictions(self) -> None:
        config = ModelConfig(seed=9, n_estimators=10, min_samples_leaf=3)
        first = ConditionalFareDistributionModel(config).fit(self.split.train)
        second = ConditionalFareDistributionModel(config).fit(self.split.train)
        context = self.split.test[1].context
        self.assertEqual(first.predict(context).to_dict(), second.predict(context).to_dict())


if __name__ == "__main__":
    unittest.main()
