"""Trusted persistence for the separate Phase-7 personalized artifact."""

from dataclasses import dataclass
import json
from pathlib import Path
import platform

import joblib
import numpy
import sklearn

from reserve_pay_optimizer import __version__
from reserve_pay_optimizer.personalization.config import (
    CHRONOLOGICAL_SPLIT_STRATEGY,
    HISTORY_FEATURE_NAMES,
    MINIMUM_PERSONALIZATION_HISTORY,
    PERSONALIZED_MODEL_VERSION,
)
from reserve_pay_optimizer.personalization.features import (
    PERSONALIZATION_FORBIDDEN_FEATURE_NAMES,
    PERSONALIZED_FEATURE_NAMES,
)
from reserve_pay_optimizer.personalization.model import PersonalizedConditionalFareDistributionModel
from reserve_pay_optimizer.personalization.training import PersonalizedTrainingResult
from reserve_pay_optimizer.prediction.config import PAISE_ROUNDING_RULE, QUANTILES, TARGET_DEFINITION, ModelConfig, quantile_key
from reserve_pay_optimizer.prediction.persistence import validate_artifact_compatibility


@dataclass(frozen=True, slots=True)
class LoadedPersonalizedArtifact:
    model: PersonalizedConditionalFareDistributionModel
    metadata: dict[str, object]


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def save_personalized_artifact(
    result: PersonalizedTrainingResult,
    directory: Path,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    models_directory = directory / "models"
    models_directory.mkdir(exist_ok=True)
    for quantile in QUANTILES:
        key = quantile_key(quantile)
        joblib.dump(
            result.model.quantile_models[key],
            models_directory / f"q_{key[2:]}.joblib",
        )
    _write_json(
        directory / "feature_schema.json",
        {
            "features": list(PERSONALIZED_FEATURE_NAMES),
            "forbidden_features": sorted(PERSONALIZATION_FORBIDDEN_FEATURE_NAMES),
            "sources": ["RideTransactionContext", "CustomerHistoryFeatures"],
        },
    )
    _write_json(
        directory / "history_feature_schema.json",
        {
            "features": list(HISTORY_FEATURE_NAMES),
            "minimum_personalization_history": MINIMUM_PERSONALIZATION_HISTORY,
            "completion_rule": "completed_at < transaction.timestamp",
            "customer_id_usage": "lookup_and_trace_only_not_model_feature",
        },
    )
    _write_json(
        directory / "evaluation_summary.json",
        {
            "validation": result.validation_evaluation.to_dict(),
            "test": result.test_evaluation.to_dict(),
        },
    )
    metadata = {
        "artifact_format_version": 1,
        "model_version": PERSONALIZED_MODEL_VERSION,
        "project_version": __version__,
        "model_type": "sklearn.ensemble.GradientBoostingRegressor",
        "loss": "quantile",
        "quantiles": [quantile_key(value) for value in QUANTILES],
        "model_config": result.model.config.to_dict(),
        "split_counts": result.split.counts,
        "personalized_training_record_count": result.personalized_training_record_count,
        "chronological_split_strategy": CHRONOLOGICAL_SPLIT_STRATEGY,
        "minimum_personalization_history": MINIMUM_PERSONALIZATION_HISTORY,
        "dataset_fingerprint_sha256": result.dataset_fingerprint,
        "target_definition": TARGET_DEFINITION,
        "prediction_amount_rounding": PAISE_ROUNDING_RULE,
        "feature_schema_file": "feature_schema.json",
        "history_feature_schema_file": "history_feature_schema.json",
        "evaluation_summary_file": "evaluation_summary.json",
        "source_dataset_metadata": result.source_metadata,
        "trusted_sources_only": True,
        "library_versions": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "numpy": numpy.__version__,
            "joblib": joblib.__version__,
        },
    }
    _write_json(directory / "metadata.json", metadata)


def load_personalized_artifact(directory: Path) -> LoadedPersonalizedArtifact:
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("model_version") != PERSONALIZED_MODEL_VERSION:
        raise ValueError(f"unsupported personalized model version: {metadata.get('model_version')}")
    validate_artifact_compatibility(metadata)
    expected_quantiles = [quantile_key(value) for value in QUANTILES]
    if metadata.get("quantiles") != expected_quantiles:
        raise ValueError("personalized artifact quantiles do not match this project")
    if metadata.get("minimum_personalization_history") != MINIMUM_PERSONALIZATION_HISTORY:
        raise ValueError("personalized artifact history threshold does not match this project")
    if metadata.get("chronological_split_strategy") != CHRONOLOGICAL_SPLIT_STRATEGY:
        raise ValueError("personalized artifact split strategy does not match this project")
    schema = json.loads((directory / "feature_schema.json").read_text(encoding="utf-8"))
    if schema.get("features") != list(PERSONALIZED_FEATURE_NAMES):
        raise ValueError("personalized artifact feature schema does not match this project")
    if schema.get("forbidden_features") != sorted(PERSONALIZATION_FORBIDDEN_FEATURE_NAMES):
        raise ValueError("personalized artifact forbidden-feature schema does not match this project")
    history_schema = json.loads(
        (directory / "history_feature_schema.json").read_text(encoding="utf-8")
    )
    if history_schema.get("features") != list(HISTORY_FEATURE_NAMES):
        raise ValueError("personalized artifact history schema does not match this project")
    if history_schema.get("completion_rule") != "completed_at < transaction.timestamp":
        raise ValueError("personalized artifact completion rule does not match this project")
    models = {
        key: joblib.load(directory / "models" / f"q_{key[2:]}.joblib")
        for key in expected_quantiles
    }
    model = PersonalizedConditionalFareDistributionModel(
        ModelConfig.from_dict(metadata["model_config"]),
        quantile_models=models,
    )
    return LoadedPersonalizedArtifact(model=model, metadata=metadata)
