"""CLOCK (Second Chance) eviction policy.

Approximates LRU with O(1) overhead using a circular scan and reference bits.
Inspired by PostgreSQL's clock-sweep buffer manager.

Each segment has a `ref_bit`. When the clock hand reaches a segment:
  - If ref_bit=1: give it a second chance (clear bit, move on)
  - If ref_bit=0: evict it
"""

from __future__ import annotations

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment


class ClockPolicy(EvictionPolicy):
    """PostgreSQL-style clock-sweep eviction."""

    def __init__(self) -> None:
        self._hand: int = 0

    @property
    def name(self) -> str:
        return "clock"

    def select_evictions(
        self, candidates: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        if not candidates:
            return []

        selected: list[Segment] = []
        freed = 0
        n = len(candidates)

        # Ensure hand is within bounds
        self._hand = self._hand % n if n > 0 else 0

        # Worst case: two full sweeps (first clears ref bits, second evicts)
        max_steps = 2 * n
        steps = 0

        while freed < tokens_to_free and steps < max_steps:
            seg = candidates[self._hand]

            if seg.ref_bit:
                # Second chance: clear the bit, move on
                seg.ref_bit = False
            else:
                # Evict this segment
                seg.evict(reason="clock:no_ref_bit", policy=self.name)
                selected.append(seg)
                freed += seg.token_count

            self._hand = (self._hand + 1) % n
            steps += 1

        return selected
