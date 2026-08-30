"""Statistical helper utilities for Phase 13 evidence.

Provides deterministic Wilson confidence interval calculation and a simple
bootstrap helper for aggregate monetary metrics.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal, ROUND_HALF_UP
from random import Random

METRIC_QUANTUM = Decimal("0.000001")


def _format(value: Decimal) -> str:
    return format(value.quantize(METRIC_QUANTUM, rounding=ROUND_HALF_UP), "f")


def wilson_ci(
    successes: int,
    trials: int,
    confidence: Decimal = Decimal("0.95"),
) -> dict[str, str]:
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
        Six-place decimal strings plus the interval method.
    """
    if isinstance(successes, bool) or not isinstance(successes, int):
        raise ValueError("successes must be an integer")
    if isinstance(trials, bool) or not isinstance(trials, int) or trials <= 0:
        raise ValueError("trials must be a positive integer")
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between zero and trials")
    if confidence != Decimal("0.95"):
        raise ValueError("Phase 13 currently supports only 95% Wilson intervals")
    z = Decimal("1.959963984540054")
    n = Decimal(trials)
    p = Decimal(successes) / n
    denominator = Decimal(1) + z * z / n
    centre = p + z * z / (Decimal(2) * n)
    margin = z * ((p * (Decimal(1) - p) + z * z / (Decimal(4) * n)) / n).sqrt()
    return {
        "point_estimate": _format(p),
        "lower": _format((centre - margin) / denominator),
        "upper": _format((centre + margin) / denominator),
        "confidence_level": _format(confidence),
        "method": "wilson_score",
    }


def bootstrap_metric(
    values: Sequence[Decimal],
    metric_fn: Callable[[Sequence[Decimal]], Decimal],
    *,
    seed: int,
    samples: int = 1_000,
) -> dict[str, str | int]:
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
        Six-place decimal strings, sample count, seed, and interval method.
    """
    if not values:
        raise ValueError("bootstrap_metric requires a non‑empty values sequence")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        raise ValueError("samples must be a positive integer")
    rng = Random(seed)
    n = len(values)
    estimates = sorted(
        metric_fn(tuple(values[rng.randrange(n)] for _ in range(n)))
        for _ in range(samples)
    )
    lower_index = max(0, int(Decimal("0.025") * samples))
    upper_index = min(samples - 1, int(Decimal("0.975") * samples))
    return {
        "point_estimate": _format(metric_fn(values)),
        "lower": _format(estimates[lower_index]),
        "upper": _format(estimates[upper_index]),
        "confidence_level": "0.950000",
        "method": "seeded_percentile_bootstrap",
        "samples": samples,
        "seed": seed,
    }


def bootstrap_mean_paise(
    values: Sequence[int],
    *,
    seed: int,
    samples: int = 1_000,
) -> dict[str, str | int]:
    """Convenience bootstrap for an average integer-paise quantity."""

    decimals = tuple(Decimal(value) for value in values)
    return bootstrap_metric(
        decimals,
        lambda sample: sum(sample, Decimal(0)) / Decimal(len(sample)),
        seed=seed,
        samples=samples,
    )
