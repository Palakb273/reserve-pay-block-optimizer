from __future__ import annotations

from pathlib import Path

from reserve_pay_optimizer.evidence.config import FinalEvidenceConfig
from reserve_pay_optimizer.web.evidence import prepare_dashboard_evidence
from reserve_pay_optimizer.web.services import DashboardSettings


def generate_final_evidence(config: FinalEvidenceConfig) -> dict[str, object]:
    """Generate the final evidence artifact for Phase 13.

    This function mirrors the dashboard evidence generation but writes the
    artifact to ``config.output`` and returns the JSON dictionary.
    """
    settings = config.settings or DashboardSettings()
    # Reuse the existing preparation logic; it already produces the required
    # fields (provenance, strategies, block_distribution, per_city, etc.).
    artifact = prepare_dashboard_evidence(
        count=config.count,
        seed=config.seed,
        output=config.output,
        settings=settings,
    )
    return artifact
