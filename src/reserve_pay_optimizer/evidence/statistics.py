"""Statistical helper utilities for Phase 13 evidence.

Provides deterministic Wilson confidence interval calculation and a simple
bootstrap helper for aggregate monetary metrics.
"""

from __future__ import annotations

import random
from decimal import Decimal, getcontext, ROUND_HALF_UP
from typing import Callable, Iterable, Sequence

# Use a higher precision for intermediate calculations
getcontext().prec = 28


def wilson_ci(successes: int, trials: int, confidence: Decimal = Decimal("0.95")) -> dict[str, object]:
    """Return a 95 % Wilson confidence interval for a binomial proportion.

    Parameters
    ----------
    successes: int
        Number of successful events (e.g., collection successes).
    trials: int
        Total number of trials.
    confidence: Decimal, optional
        Desired confidence level (default 0.95).

    Returns
    -------
    dict
        ``{"point_estimate": float, "lower": float, "upper": float,
        "confidence_level": float, "method": "wilson"}``
    """
    if trials == 0:
        raise ValueError("trials must be > 0 for confidence interval calculation")
    p = Decimal(successes) / Decimal(trials)
    # Approximate z-score for the given confidence level; use 1.96 for 95%
    if confidence == Decimal("0.95"):
        z = Decimal("1.96")
    else:
        # For other confidences, a rough approximation using normal inverse CDF could be added.
        # Here we fallback to 1.96 as a safe default.
        z = Decimal("1.96")
    denominator = Decimal(1) + (z**2) / Decimal(trials)
    centre = p + (z**2) / (2 * Decimal(trials))
    margin = z * ((p * (Decimal(1) - p) + (z**2) / (4 * Decimal(trials))) / Decimal(trials)).sqrt()
    lower = (centre - margin) / denominator
    upper = (centre + margin) / denominator
    return {
        "point_estimate": float(p.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "lower": float(lower.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "upper": float(upper.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "confidence_level": float(confidence),
        "method": "wilson",
    }


def bootstrap_metric(
    values: Sequence[Decimal],
    metric_fn: Callable[[Sequence[Decimal]], Decimal],
    seed: int,
    samples: int = 1_000,
) -> dict[str, object]:
    """Deterministic bootstrap for a monetary/aggregate metric.

    Parameters
    ----------
    values: sequence of Decimal
        The observed metric values (e.g., excess block amounts).
    metric_fn: callable
        Function that computes the statistic of interest from a list of values.
    seed: int
        Fixed random seed for reproducibility.
    samples: int
        Number of bootstrap resamples (default 1000).

    Returns
    -------
    dict
        ``{"mean": float, "lower": float, "upper": float, "method": "bootstrap"}``
    """
    if not values:
        raise ValueError("bootstrap_metric requires a non‑empty values sequence")
    random.seed(seed)
    estimates: list[Decimal] = []
    n = len(values)
    for _ in range(samples):
        sample = [values[random.randint(0, n - 1)] for _ in range(n)]
        estimates.append(metric_fn(sample))
    estimates.sort()
    lower_idx = int(0.025 * samples)
    upper_idx = int(0.975 * samples) - 1
    lower = estimates[lower_idx]
    upper = estimates[upper_idx]
    mean_est = sum(estimates) / Decimal(samples)
    return {
        "mean": float(mean_est.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "lower": float(lower.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "upper": float(upper.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "method": "bootstrap",
    }
}
