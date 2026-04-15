"""Budget-aware composite eviction policy.

Combines a scoring signal (composite_score from the Scorer) with a hard
token budget. Evicts the lowest-scoring segments first until budget is met.

When no scores are available, falls back to LRU ordering.
"""

from __future__ import annotations

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment


class BudgetAwarePolicy(EvictionPolicy):
    """Score-based eviction with LRU fallback."""

    @property
    def name(self) -> str:
        return "budget_aware"

    def select_evictions(
        self, candidates: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        # Partition: scored vs unscored
        scored = [s for s in candidates if s.composite_score is not None]
        unscored = [s for s in candidates if s.composite_score is None]

        # Score ascending (lowest score = evict first)
        scored.sort(key=lambda s: s.composite_score or 0.0)
        # Unscored fallback to LRU
        unscored.sort(key=lambda s: s.last_accessed)

        # Interleave: evict low-scoring first, then LRU unscored
        ranked = scored + unscored
        return self._fill_to_budget(ranked, tokens_to_free)

    def _reason(self, seg: Segment) -> str:
        if seg.composite_score is not None:
            return f"budget:score={seg.composite_score:.3f}"
        return f"budget:lru_fallback:idle_{seg.idle_seconds:.0f}s"
