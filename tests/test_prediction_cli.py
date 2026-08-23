from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reserve_pay_optimizer.cli import main
from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions


class PredictionCliTests(unittest.TestCase):
    def test_simulator_to_training_evaluation_and_unseen_inference_workflow(self) -> None:
        dataset = simulate_transactions(SimulationConfig(transaction_count=60, seed=73))
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dataset_path = directory / "dataset.json"
            context_path = directory / "context.json"
            artifact_path = directory / "artifact"
            dataset_path.write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
            context_path.write_text(
                json.dumps(dataset.records[-1].to_dict()["transaction"]), encoding="utf-8"
            )

            stream = StringIO()
            with redirect_stdout(stream):
                status = main([
                    "train-predictor", "--file", str(dataset_path), "--seed", "73",
                    "--output", str(artifact_path),
                ])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(stream.getvalue())["training_records"], 42)

            stream = StringIO()
            with redirect_stdout(stream):
                status = main([
                    "evaluate-predictor", "--file", str(dataset_path),
                    "--model", str(artifact_path),
                ])
            evaluation = json.loads(stream.getvalue())
            self.assertEqual(status, 0)
            self.assertEqual(evaluation["evaluation_scope"], "held_out_test_split")
            self.assertEqual(evaluation["test_records"], 9)

            stream = StringIO()
            with redirect_stdout(stream):
                status = main([
                    "predict-distribution", "--model", str(artifact_path),
                    "--file", str(context_path),
                ])
            prediction = json.loads(stream.getvalue())
            self.assertEqual(status, 0)
            self.assertEqual(len(prediction["quantiles"]), 10)
            self.assertNotIn("recommended_reserve_amount", prediction)


if __name__ == "__main__":
    unittest.main()
