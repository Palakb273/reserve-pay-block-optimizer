import unittest

from reserve_pay_optimizer.prediction.config import ModelConfig
from reserve_pay_optimizer.prediction.dataset import (
    build_prediction_records,
    dataset_fingerprint,
    split_records,
)
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class PredictionDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dataset = simulate_transactions(SimulationConfig(transaction_count=40, seed=19))
        cls.contexts = tuple(record.transaction for record in dataset.records)
        cls.outcomes = tuple(record.outcome for record in dataset.records)
        cls.records = build_prediction_records(cls.contexts, cls.outcomes)

    def test_same_seed_produces_same_disjoint_complete_split(self) -> None:
        config = ModelConfig(seed=7)
        first = split_records(self.records, config)
        second = split_records(self.records, config)
        first_ids = tuple(record.context.transaction_id for record in first.train)
        self.assertEqual(first_ids, tuple(record.context.transaction_id for record in second.train))
        sets = [
            {record.context.transaction_id for record in partition}
            for partition in (first.train, first.validation, first.test)
        ]
        self.assertTrue(sets[0].isdisjoint(sets[1]))
        self.assertTrue(sets[0].isdisjoint(sets[2]))
        self.assertTrue(sets[1].isdisjoint(sets[2]))
        self.assertEqual(sum(map(len, sets)), len(self.records))
        self.assertEqual(first.counts, {"train": 28, "validation": 6, "test": 6})

    def test_different_seed_changes_split(self) -> None:
        first = split_records(self.records, ModelConfig(seed=1))
        second = split_records(self.records, ModelConfig(seed=2))
        self.assertNotEqual(first.train, second.train)

    def test_fingerprint_is_content_and_config_sensitive(self) -> None:
        first = dataset_fingerprint(self.records, ModelConfig(seed=42))
        reordered = build_prediction_records(tuple(reversed(self.contexts)), tuple(reversed(self.outcomes)))
        self.assertEqual(first, dataset_fingerprint(reordered, ModelConfig(seed=42)))
        self.assertNotEqual(first, dataset_fingerprint(self.records, ModelConfig(seed=43)))
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
