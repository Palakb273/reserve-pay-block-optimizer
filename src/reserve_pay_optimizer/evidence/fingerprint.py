"""Canonical evidence serialization and reproducibility fingerprints."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any


_OBSERVATIONAL_AGENT_FIELDS = {
    "average_execution_time_ms",
    "median_execution_time_ms",
    "p95_execution_time_ms",
}


def canonical_evidence_payload(artifact: dict[str, Any]) -> bytes:
    """Return canonical metric content, excluding self-reference and wall-clock timing.

    Agent timing is measured, not fabricated, and is deliberately outside the
    reproducibility hash. All financial metrics and configuration remain covered.
    """

    value = deepcopy(artifact)
    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("evidence_fingerprint_sha256", None)
    agents = value.get("agents")
    if isinstance(agents, dict):
        for field in _OBSERVATIONAL_AGENT_FIELDS:
            agents.pop(field, None)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def evidence_fingerprint(artifact: dict[str, Any]) -> str:
    return sha256(canonical_evidence_payload(artifact)).hexdigest()

