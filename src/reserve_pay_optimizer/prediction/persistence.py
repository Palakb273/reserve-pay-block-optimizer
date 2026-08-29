"""Trusted project-local joblib persistence for Phase 4 model artifacts.

Joblib uses Python pickle semantics. Only load artifacts created by and obtained
from a trusted project source; never load arbitrary or user-uploaded artifacts.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import platform

import joblib
import numpy
import sklearn

from reserve_pay_optimizer import __version__
from reserve_pay_optimizer.prediction.baseline import GlobalQuantileBaseline
from reserve_pay_optimizer.prediction.config import (
    MODEL_VERSION,
    PAISE_ROUNDING_RULE,
    QUANTILES,
    TARGET_DEFINITION,
    ModelConfig,
    quantile_key,
)
from reserve_pay_optimizer.prediction.features import (
    FEATURE_NAMES,
    FORBIDDEN_FEATURE_NAMES,
)
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel
from reserve_pay_optimizer.prediction.training import TrainingResult


@dataclass(frozen=True, slots=True)
class LoadedPredictorArtifact:
    model: ConditionalFareDistributionModel
    metadata: dict[str, object]


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_artifact_compatibility(metadata: dict[str, object]) -> None:
    """Fail before joblib loading when serialized-library versions differ."""

    versions = metadata.get("library_versions")
    if not isinstance(versions, dict):
        raise ValueError("artifact does not contain required library-version metadata")
    expected = {
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }
    for library, runtime_version in expected.items():
        artifact_version = versions.get(library)
        if artifact_version != runtime_version:
            raise ValueError(
                f"incompatible trusted artifact: {library} {artifact_version!r} was "
                f"used for serialization, but runtime {runtime_version!r} is installed; "
                "use the recorded library version or retrain the model"
            )


def save_predictor_artifact(result: TrainingResult, directory: Path) -> None:
    """Persist each fitted quantile model plus fully inspectable metadata."""

    directory.mkdir(parents=True, exist_ok=True)
    models_directory = directory / "models"
    models_directory.mkdir(exist_ok=True)
    for quantile in QUANTILES:
        key = quantile_key(quantile)
        joblib.dump(result.model.quantile_models[key], models_directory / f"q_{key[2:]}.joblib")

    baseline = result.model.baseline
    if baseline is None:
        raise RuntimeError("cannot persist a model without its fitted global baseline")
    _write_json(directory / "baseline_ratios.json", baseline.to_dict())
    _write_json(
        directory / "feature_schema.json",
        {
            "features": list(FEATURE_NAMES),
            "forbidden_features": sorted(FORBIDDEN_FEATURE_NAMES),
            "source_type": "RideTransactionContext",
        },
    )
    evaluation = {
        "validation": result.validation_evaluation.to_dict(),
        "test": result.test_evaluation.to_dict(),
    }
    _write_json(directory / "evaluation_summary.json", evaluation)
    metadata = {
        "artifact_format_version": 1,
        "model_version": MODEL_VERSION,
        "project_version": __version__,
        "model_type": "sklearn.ensemble.GradientBoostingRegressor",
        "loss": "quantile",
        "quantiles": [quantile_key(value) for value in QUANTILES],
        "model_config": result.model.config.to_dict(),
        "split_counts": result.split.counts,
        "dataset_fingerprint_sha256": result.dataset_fingerprint,
        "target_definition": TARGET_DEFINITION,
        "prediction_amount_rounding": PAISE_ROUNDING_RULE,
        "feature_schema_file": "feature_schema.json",
        "evaluation_summary_file": "evaluation_summary.json",
        "trusted_sources_only": True,
        "library_versions": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "numpy": numpy.__version__,
            "joblib": joblib.__version__,
        },
    }
    _write_json(directory / "metadata.json", metadata)


def load_predictor_artifact(directory: Path) -> LoadedPredictorArtifact:
    """Load a trusted project artifact after validating its inspectable schema."""

    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("model_version") != MODEL_VERSION:
        raise ValueError(f"unsupported model version: {metadata.get('model_version')}")
    validate_artifact_compatibility(metadata)
    expected_quantiles = [quantile_key(value) for value in QUANTILES]
    if metadata.get("quantiles") != expected_quantiles:
        raise ValueError("artifact quantile configuration does not match this project")
    schema = json.loads((directory / "feature_schema.json").read_text(encoding="utf-8"))
    if schema.get("features") != list(FEATURE_NAMES):
        raise ValueError("artifact feature schema does not match this project")
    models = {
        key: joblib.load(directory / "models" / f"q_{key[2:]}.joblib")
        for key in expected_quantiles
    }
    baseline_values = json.loads((directory / "baseline_ratios.json").read_text(encoding="utf-8"))
    baseline = GlobalQuantileBaseline.from_dict(baseline_values)
    model = ConditionalFareDistributionModel(
        ModelConfig.from_dict(metadata["model_config"]),
        quantile_models=models,
        baseline=baseline,
    )
    return LoadedPredictorArtifact(model=model, metadata=metadata)
