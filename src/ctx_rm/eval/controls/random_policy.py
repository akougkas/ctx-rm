"""RandomPolicy: evicts uniformly at random, seeded for reproducibility.

RandomPolicy is the *lower bound* for the L1 evaluation. Any shipped policy
should beat random by a statistically significant margin; if it doesn't,
that's a regression signal. The PRNG is seeded per-instance so the same
seed produces the same run across machines.
"""

from __future__ import annotations

import random

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment


class RandomPolicy(EvictionPolicy):
    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return "random"

    def select_evictions(self, candidates: list[Segment], tokens_to_free: int) -> list[Segment]:
        if not candidates or tokens_to_free <= 0:
            return []
        pool = list(candidates)
        self._rng.shuffle(pool)
        return self._fill_to_budget(pool, tokens_to_free)

    def _reason(self, seg: Segment) -> str:
        return "random"
