"""LRU (Least Recently Used) eviction policy.

The simplest and most predictable policy. Evicts the segments with the
oldest `last_accessed` timestamp first. Equivalent to OS page replacement
with pure recency ordering.
"""

from __future__ import annotations

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment


class LRUPolicy(EvictionPolicy):
    """Evict the least recently accessed segments first."""

    @property
    def name(self) -> str:
        return "lru"

    def select_evictions(
        self, candidates: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        # Sort by last_accessed ascending (oldest access first)
        ranked = sorted(candidates, key=lambda s: s.last_accessed)
        return self._fill_to_budget(ranked, tokens_to_free)

    def _reason(self, seg: Segment) -> str:
        return f"lru:idle_{seg.idle_seconds:.0f}s"
