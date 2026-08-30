"""Deterministic Phase-13 evaluation datasets and canonical fingerprints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reserve_pay_optimizer.simulation.config import SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions
from reserve_pay_optimizer.simulation.models import SimulationDataset


def generate_dataset(
    *, count: int, seed: int, customer_pool_size: int
) -> SimulationDataset:
    """Generate one fresh, reproducible, customer-aware evaluation cohort."""

    return simulate_transactions(
        SimulationConfig(
            transaction_count=count,
            seed=seed,
            customer_pool_size=customer_pool_size,
            customer_behavior_enabled=True,
        )
    )


def dataset_fingerprint(dataset: SimulationDataset) -> str:
    """Hash canonical contents and simulator configuration without local paths."""

    encoded = json.dumps(
        dataset.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_dataset(dataset: SimulationDataset, path: Path) -> Path:
    """Write a generated dataset only when an explicit export is wanted.

    The function creates parent directories as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dataset.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
