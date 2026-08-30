"""Configuration for the final evidence generation (Phase 13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reserve_pay_optimizer.policy.risk import RiskProfile


@dataclass(frozen=True, slots=True)
class FinalEvidenceConfig:
    """Deterministic configuration used to generate the authoritative evidence.

    The defaults follow the specification for the authoritative run. All values are
    validated on instantiation via :meth:`validate`.
    """

    # Core dataset parameters
    transaction_count: int = 20_000
    dataset_seed: int = 202_613
    customer_pool_size: int = 5_000

    # Dynamic re‑optimisation parameters
    dynamic_seed: int = 202_714
    dynamic_record_count: int = 5_000

    # Agent cohort size
    agent_record_count: int = 500

    # Bootstrap parameters for statistical confidence
    bootstrap_seed: int = 202_815
    bootstrap_samples: int = 1_000

    # Primary risk profile used for the optimized balanced strategy
    primary_risk_profile: str = "balanced"

    base_model_path: Path = field(
        default_factory=lambda: Path("artifacts/prediction/fare_distribution_v1")
    )
    personalized_model_path: Path = field(
        default_factory=lambda: Path(
            "artifacts/prediction/fare_distribution_personalized_v1"
        )
    )

    # Output location for the generated artifact
    output_path: Path = field(default_factory=lambda: Path("demo/evidence/final_evidence.json"))

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate the configuration values.

        Raises
        ------
        ValueError
            If any of the constraints from the specification are violated.
        """
        count_fields = (
            "transaction_count",
            "customer_pool_size",
            "dynamic_record_count",
            "agent_record_count",
            "bootstrap_samples",
        )
        for field_name in count_fields:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
        for field_name in ("dataset_seed", "dynamic_seed", "bootstrap_seed"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
        if self.transaction_count < 10_000:
            raise ValueError("transaction_count must be >= 10,000 for authoritative evidence")
        if self.customer_pool_size <= 0:
            raise ValueError("customer_pool_size must be > 0")
        if self.dynamic_record_count <= 0:
            raise ValueError("dynamic_record_count must be > 0")
        if self.dynamic_record_count > self.transaction_count:
            raise ValueError("dynamic_record_count cannot exceed transaction_count")
        if self.agent_record_count <= 0:
            raise ValueError("agent_record_count must be > 0")
        if self.agent_record_count > self.transaction_count:
            raise ValueError("agent_record_count cannot exceed transaction_count")
        if self.bootstrap_samples <= 0:
            raise ValueError("bootstrap_samples must be > 0")
        try:
            RiskProfile(self.primary_risk_profile)
        except ValueError as exc:
            raise ValueError("primary_risk_profile must be a supported risk profile") from exc
        for field_name in ("base_model_path", "personalized_model_path", "output_path"):
            if not isinstance(getattr(self, field_name), Path):
                raise ValueError(f"{field_name} must be a pathlib.Path instance")

    def to_dict(self) -> dict[str, object]:
        """Serialize only reproducibility inputs, never machine-specific paths."""

        return {
            "transaction_count": self.transaction_count,
            "dataset_seed": self.dataset_seed,
            "customer_pool_size": self.customer_pool_size,
            "dynamic_seed": self.dynamic_seed,
            "dynamic_record_count": self.dynamic_record_count,
            "agent_record_count": self.agent_record_count,
            "bootstrap_seed": self.bootstrap_seed,
            "bootstrap_samples": self.bootstrap_samples,
            "primary_risk_profile": self.primary_risk_profile,
        }
