"""Base protocol for eviction policies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ctx_rm.core.segment import Segment


class EvictionPolicy(ABC):
    """Abstract base for eviction policies.

    Given a list of candidate segments and a token target to free,
    returns the ordered list of segments to evict.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Policy identifier for audit logs."""

    @abstractmethod
    def select_evictions(
        self, candidates: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        """Select which segments to evict to free at least `tokens_to_free` tokens.

        Args:
            candidates: Non-pinned segments eligible for eviction.
            tokens_to_free: Minimum tokens to reclaim.

        Returns:
            Ordered list of segments to evict (first = evict first).
        """

    def _fill_to_budget(
        self, ranked: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        """Helper: greedily select from a ranked list until budget is met."""
        selected: list[Segment] = []
        freed = 0
        for seg in ranked:
            if freed >= tokens_to_free:
                break
            seg.evict(reason=self._reason(seg), policy=self.name)
            selected.append(seg)
            freed += seg.token_count
        return selected

    def _reason(self, seg: Segment) -> str:
        """Default eviction reason — subclasses can override."""
        return f"policy:{self.name}"
