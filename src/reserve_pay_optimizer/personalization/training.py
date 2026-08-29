"""Chronological personalized model training orchestration."""

from dataclasses import dataclass

from reserve_pay_optimizer.domain.mobility import RideTransactionContext, RideTransactionOutcome
from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY
from reserve_pay_optimizer.personalization.dataset import (
    ChronologicalDatasetSplit,
    build_personalized_records,
    chronological_split,
    personalized_dataset_fingerprint,
)
from reserve_pay_optimizer.personalization.evaluation import PersonalizationEvaluation, evaluate_personalization
from reserve_pay_optimizer.personalization.model import PersonalizedConditionalFareDistributionModel
from reserve_pay_optimizer.prediction.config import QUANTILES, ModelConfig, quantile_key
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


@dataclass(frozen=True, slots=True)
class PersonalizedTrainingResult:
    model: PersonalizedConditionalFareDistributionModel
    split: ChronologicalDatasetSplit
    dataset_fingerprint: str
    personalized_training_record_count: int
    validation_evaluation: PersonalizationEvaluation
    test_evaluation: PersonalizationEvaluation
    source_metadata: dict[str, object] | None = None

    def summary(self, artifact_path: str) -> dict[str, object]:
        return {
            "training_status": "complete",
            "training_records": len(self.split.train),
            "personalized_training_records": self.personalized_training_record_count,
            "validation_records": len(self.split.validation),
            "test_records": len(self.split.test),
            "minimum_personalization_history": MINIMUM_PERSONALIZATION_HISTORY,
            "quantiles": [quantile_key(value) for value in QUANTILES],
            "model_version": self.model.model_version,
            "model_artifact": artifact_path,
            "dataset_fingerprint": self.dataset_fingerprint,
        }


def train_personalized_predictor(
    contexts: tuple[RideTransactionContext, ...],
    outcomes: tuple[RideTransactionOutcome, ...],
    base_model: ConditionalFareDistributionModel,
    config: ModelConfig | None = None,
    *,
    source_metadata: dict[str, object] | None = None,
) -> PersonalizedTrainingResult:
    resolved = config or ModelConfig()
    records = build_personalized_records(contexts, outcomes)
    split = chronological_split(records, resolved)
    eligible_train = tuple(
        record
        for record in split.train
        if record.history.completed_ride_count >= MINIMUM_PERSONALIZATION_HISTORY
    )
    model = PersonalizedConditionalFareDistributionModel(resolved).fit(eligible_train)
    return PersonalizedTrainingResult(
        model=model,
        split=split,
        dataset_fingerprint=personalized_dataset_fingerprint(records, resolved),
        personalized_training_record_count=len(eligible_train),
        validation_evaluation=evaluate_personalization(
            model, base_model, split.validation
        ),
        test_evaluation=evaluate_personalization(model, base_model, split.test),
        source_metadata=source_metadata,
    )

