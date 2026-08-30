"""Configuration for the final evidence generation (Phase 13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
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

    # Output location for the generated artifact
    output_path: Path = field(default_factory=lambda: Path("demo/evidence/final_evidence.json"))

    def validate(self) -> None:
        """Validate the configuration values.

        Raises
        ------
        ValueError
            If any of the constraints from the specification are violated.
        """
        if self.transaction_count < 10_000:
            raise ValueError("transaction_count must be >= 10,000 for authoritative evidence")
        if self.customer_pool_size <= 0:
            raise ValueError("customer_pool_size must be > 0")
        if self.dynamic_record_count <= 0:
            raise ValueError("dynamic_record_count must be > 0")
        if self.agent_record_count <= 0:
            raise ValueError("agent_record_count must be > 0")
        if self.bootstrap_samples <= 0:
            raise ValueError("bootstrap_samples must be > 0")
        if not isinstance(self.output_path, Path):
            raise ValueError("output_path must be a pathlib.Path instance")

