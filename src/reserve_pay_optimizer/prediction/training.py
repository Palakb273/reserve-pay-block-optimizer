"""End-to-end deterministic model training orchestration."""

from dataclasses import dataclass

from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.prediction.config import QUANTILES, ModelConfig, quantile_key
from reserve_pay_optimizer.prediction.dataset import (
    DatasetSplit,
    build_prediction_records,
    dataset_fingerprint,
    split_records,
)
from reserve_pay_optimizer.prediction.evaluation import PredictorEvaluation, evaluate_predictor
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: ConditionalFareDistributionModel
    split: DatasetSplit
    dataset_fingerprint: str
    validation_evaluation: PredictorEvaluation
    test_evaluation: PredictorEvaluation

    def summary(self, artifact_path: str) -> dict[str, object]:
        return {
            "training_status": "complete",
            "training_records": len(self.split.train),
            "validation_records": len(self.split.validation),
            "test_records": len(self.split.test),
            "quantiles": [quantile_key(value) for value in QUANTILES],
            "model_version": self.model.model_version,
            "model_artifact": artifact_path,
            "dataset_fingerprint": self.dataset_fingerprint,
        }


def train_predictor(
    contexts: tuple[RideTransactionContext, ...],
    outcomes: tuple[RideTransactionOutcome, ...],
    config: ModelConfig | None = None,
) -> TrainingResult:
    resolved_config = config or ModelConfig()
    records = build_prediction_records(contexts, outcomes)
    split = split_records(records, resolved_config)
    model = ConditionalFareDistributionModel(resolved_config).fit(split.train)
    return TrainingResult(
        model=model,
        split=split,
        dataset_fingerprint=dataset_fingerprint(records, resolved_config),
        validation_evaluation=evaluate_predictor(model, split.validation),
        test_evaluation=evaluate_predictor(model, split.test),
    )
