"""Dataset generation utilities for Phase 13 final evidence.

This module provides a deterministic transaction dataset generator used by the final
evidence pipeline. It delegates to the existing transaction simulator while
exposing additional helpers for metadata, fingerprinting, and JSON serialisation.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import List, Dict

from reserve_pay_optimizer.simulation.generator import simulate_transactions


def generate_dataset(count: int = 10_000, seed: int = 202611) -> List[dict[str, object]]:
    """Generate a deterministic list of transaction records.

    Args:
        count: Number of transactions to simulate. Defaults to the Phase 11 demo
            size of 10 000.
        seed: Random seed for deterministic simulation. The same seed must be
            used for reproducibility across runs and CI.

    Returns:
        A list of transaction dictionaries suitable for JSON dumping and
        downstream evidence calculations.
    """
    transactions = simulate_transactions(count=count, seed=seed)
    return [tx.to_dict() for tx in transactions]


def write_dataset(path: Path, count: int = 10_000, seed: int = 202611) -> Path:
    """Write the generated dataset to *path* as pretty‑printed JSON.

    The function creates parent directories as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset = generate_dataset(count=count, seed=seed)
    import json
    with path.open("w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    return path
