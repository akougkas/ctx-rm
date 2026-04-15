"""Nonparametric bootstrap confidence intervals.

We use the percentile bootstrap: resample the input with replacement B times,
compute the statistic on each resample, take the p/2 and 1-p/2 percentiles
of the resampled distribution. No distributional assumptions. With
`iterations=1000` and `seed` pinned, results are reproducible across runs.

Why this instead of t-intervals? Our per-trace metrics are bounded in [0, 1],
highly non-normal (retention clusters near 1 on abundant-budget runs), and
we have small sample sizes (dozens of traces, not thousands). Bootstrap is
the safe default.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class BootstrapCI:
    mean: float
    low: float
    high: float
    n: int

    def __str__(self) -> str:
        return f"{self.mean:.3f} [{self.low:.3f}, {self.high:.3f}] n={self.n}"


def bootstrap_mean_ci(
    values: list[float],
    *,
    iterations: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
) -> BootstrapCI:
    """Percentile-bootstrap CI for the sample mean."""
    n = len(values)
    if n == 0:
        return BootstrapCI(mean=float("nan"), low=float("nan"), high=float("nan"), n=0)
    if n == 1:
        return BootstrapCI(mean=values[0], low=values[0], high=values[0], n=1)

    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()

    mean = sum(values) / n
    lo_idx = max(0, math.floor((alpha / 2) * iterations))
    hi_idx = min(iterations - 1, math.ceil((1 - alpha / 2) * iterations) - 1)
    return BootstrapCI(mean=mean, low=means[lo_idx], high=means[hi_idx], n=n)
