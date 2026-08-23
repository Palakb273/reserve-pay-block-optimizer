"""Central configuration for the first learned prediction engine."""

from dataclasses import asdict, dataclass
from decimal import Decimal

MODEL_VERSION = "fare_distribution_v1"
TARGET_DEFINITION = "fare_ratio=actual_amount_paise/estimated_amount_paise"
PAISE_ROUNDING_RULE = "ceiling_to_next_paise"

QUANTILES: tuple[Decimal, ...] = tuple(
    Decimal(value)
    for value in (
        "0.05",
        "0.10",
        "0.25",
        "0.50",
        "0.75",
        "0.90",
        "0.93",
        "0.95",
        "0.97",
        "0.99",
    )
)


def quantile_key(quantile: Decimal) -> str:
    """Return the stable JSON/model-file key for a configured quantile."""

    return f"{quantile:.2f}"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Deterministic split and gradient-boosting configuration."""

    seed: int = 42
    train_fraction: Decimal = Decimal("0.70")
    validation_fraction: Decimal = Decimal("0.15")
    test_fraction: Decimal = Decimal("0.15")
    n_estimators: int = 80
    learning_rate: float = 0.05
    max_depth: int = 3
    min_samples_leaf: int = 10
    subsample: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        fractions = (
            self.train_fraction,
            self.validation_fraction,
            self.test_fraction,
        )
        if any(not isinstance(value, Decimal) or value <= 0 for value in fractions):
            raise ValueError("split fractions must be positive Decimal values")
        if sum(fractions) != Decimal(1):
            raise ValueError("train/validation/test fractions must sum to 1")
        if self.n_estimators <= 0 or self.max_depth <= 0 or self.min_samples_leaf <= 0:
            raise ValueError("tree hyperparameters must be positive")
        if self.learning_rate <= 0 or not 0 < self.subsample <= 1:
            raise ValueError("learning_rate and subsample must be in valid ranges")

    def to_dict(self) -> dict[str, object]:
        values = asdict(self)
        for field in ("train_fraction", "validation_fraction", "test_fraction"):
            values[field] = str(values[field])
        return values

    @classmethod
    def from_dict(cls, values: dict[str, object]) -> "ModelConfig":
        normalized = dict(values)
        for field in ("train_fraction", "validation_fraction", "test_fraction"):
            normalized[field] = Decimal(str(normalized[field]))
        return cls(**normalized)  # type: ignore[arg-type]
