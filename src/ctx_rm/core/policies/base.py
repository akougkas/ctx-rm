"""Base protocol for eviction policies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ctx_rm.core.segment import Segment


class EvictionPolicy(ABC):
    """Abstract base for eviction policies.

    Given a list of candidate segments and a token target to free,
    returns the ordered list of segments to evict.

    Aggressiveness
    --------------
    The adaptive feedback loop can push a policy toward evicting more or
    less than the nominal `tokens_to_free` request via `set_aggressiveness`.
    A multiplier > 1 scales the effective free target up (evict more — e.g.
    when recall rate is low and extra headroom is cheap); a multiplier < 1
    scales it down (evict less — e.g. when evicted segments keep getting
    recalled and churn is costly). The base class applies the multiplier in
    `_fill_to_budget` so every policy honors it without per-subclass changes.
    """

    # Default: honor the caller's tokens_to_free exactly.
    _aggressiveness: float = 1.0
    # Safe clamp bounds so adaptive shifts cannot turn eviction into a no-op
    # or force the policy to free 10x more than necessary.
    _AGGRESSIVENESS_MIN: float = 0.5
    _AGGRESSIVENESS_MAX: float = 2.0

    @property
    @abstractmethod
    def name(self) -> str:
        """Policy identifier for audit logs."""

    @abstractmethod
    def select_evictions(self, candidates: list[Segment], tokens_to_free: int) -> list[Segment]:
        """Select which segments to evict to free at least `tokens_to_free` tokens.

        Args:
            candidates: Non-pinned segments eligible for eviction.
            tokens_to_free: Minimum tokens to reclaim.

        Returns:
            Ordered list of segments to evict (first = evict first).
        """

    def set_aggressiveness(self, value: float) -> None:
        """Tune how much to over- or under-free relative to tokens_to_free.

        Values are clamped to [_AGGRESSIVENESS_MIN, _AGGRESSIVENESS_MAX].
        Called by ContextBus after each adaptive feedback cycle.
        """
        if value != value:  # NaN guard
            return
        self._aggressiveness = max(
            self._AGGRESSIVENESS_MIN,
            min(self._AGGRESSIVENESS_MAX, float(value)),
        )

    @property
    def aggressiveness(self) -> float:
        return self._aggressiveness

    def _scaled_free_target(self, tokens_to_free: int) -> int:
        """Apply the aggressiveness multiplier to the free target.

        Floors at `tokens_to_free` so a conservative shift (mult < 1) cannot
        leave the bus over-budget — under-freeing is not a valid mode because
        the bus runs one eviction cycle per ingest, not a loop. A multiplier
        > 1 causes the policy to over-free, building extra headroom.
        """
        if tokens_to_free <= 0:
            return 0
        scaled = int(round(tokens_to_free * self._aggressiveness))
        return max(tokens_to_free, scaled)

    def _fill_to_budget(self, ranked: list[Segment], tokens_to_free: int) -> list[Segment]:
        """Helper: greedily select from a ranked list until budget is met."""
        target = self._scaled_free_target(tokens_to_free)
        selected: list[Segment] = []
        freed = 0
        for seg in ranked:
            if freed >= target:
                break
            seg.evict(reason=self._reason(seg), policy=self.name)
            selected.append(seg)
            freed += seg.token_count
        return selected

    # ── Lifecycle hooks (optional, default no-ops) ─────────────────────

    def on_ingest(self, seg: Segment) -> None:
        """Called when a segment is ingested into active context."""
        pass

    def on_access(self, seg: Segment) -> None:
        """Called when a segment is recalled/accessed."""
        pass

    def on_evict(self, seg: Segment) -> None:
        """Called when a segment is evicted from active context."""
        pass

    def _reason(self, seg: Segment) -> str:
        """Default eviction reason — subclasses can override."""
        return f"policy:{self.name}"
