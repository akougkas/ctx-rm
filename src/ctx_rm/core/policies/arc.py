"""ARC (Adaptive Replacement Cache) eviction policy.

Implements the ARC algorithm (Megiddo & Modak, 2003) adapted for token-based
context eviction. ARC self-tunes the balance between recency (T1) and
frequency (T2) using ghost lists (B1/B2) that track recently evicted segment
metadata without storing content.

Key properties:
  - T1: recently seen once (recency list)
  - T2: seen more than once (frequency list)
  - B1: ghost list for T1 evictions (seg_id + token_count only)
  - B2: ghost list for T2 evictions (seg_id + token_count only)
  - p: adaptive parameter that shifts eviction pressure between T1 and T2

When a ghost hit occurs on B1, p increases (favor recency).
When a ghost hit occurs on B2, p decreases (favor frequency).
"""

from __future__ import annotations

from collections import OrderedDict

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment


class ARCPolicy(EvictionPolicy):
    """Adaptive Replacement Cache eviction policy.

    Maintains T1/T2 recency/frequency lists and B1/B2 ghost lists internally.
    The adaptive parameter p shifts toward T1 on B1 ghost hit and toward T2
    on B2 ghost hit.
    """

    def __init__(self, capacity_tokens: int) -> None:
        self._capacity = capacity_tokens

        # T1: segments seen once (recency), T2: segments seen >1 time (frequency)
        # OrderedDict preserves insertion order; oldest is first.
        self._t1: OrderedDict[str, int] = OrderedDict()  # seg_id -> token_count
        self._t2: OrderedDict[str, int] = OrderedDict()  # seg_id -> token_count

        # Ghost lists: metadata only (seg_id -> token_count), no content
        self._b1: OrderedDict[str, int] = OrderedDict()
        self._b2: OrderedDict[str, int] = OrderedDict()

        # Adaptive parameter: target size of T1 in tokens
        self._p: float = 0.0

    @property
    def name(self) -> str:
        return "arc"

    # ── Lifecycle hooks ──────────────────────────────────────────────

    def on_ingest(self, seg: Segment) -> None:
        """Handle segment ingestion: ghost hit detection + list placement."""
        sid = seg.seg_id
        tc = seg.token_count

        # Case 1: Ghost hit on B1 -> increase p (favor recency)
        if sid in self._b1:
            ghost_tc = self._b1.pop(sid)
            # Adapt: increase p by at least 1 token, scaled by relative sizes
            b2_tokens = sum(self._b2.values()) or 1
            b1_tokens = sum(self._b1.values()) or 1
            delta = max(1, (b2_tokens / b1_tokens) * ghost_tc)
            self._p = min(self._p + delta, float(self._capacity))
            # Promote to T2 (it was evicted from T1, now coming back -> frequency)
            self._t2[sid] = tc
            return

        # Case 2: Ghost hit on B2 -> decrease p (favor frequency)
        if sid in self._b2:
            ghost_tc = self._b2.pop(sid)
            b1_tokens = sum(self._b1.values()) or 1
            b2_tokens = sum(self._b2.values()) or 1
            delta = max(1, (b1_tokens / b2_tokens) * ghost_tc)
            self._p = max(self._p - delta, 0.0)
            # Promote to T2
            self._t2[sid] = tc
            return

        # Case 3: Already tracked in T1 or T2 (re-ingest)
        if sid in self._t1 or sid in self._t2:
            return

        # Case 4: New segment -> add to T1 (recency)
        self._t1[sid] = tc

    def on_access(self, seg: Segment) -> None:
        """Promote T1 -> T2 on access, or refresh T2 position."""
        sid = seg.seg_id

        if sid in self._t1:
            # Promote from recency to frequency
            tc = self._t1.pop(sid)
            self._t2[sid] = tc
        elif sid in self._t2:
            # Refresh position in T2 (move to end = most recent)
            self._t2.move_to_end(sid)

    def on_evict(self, seg: Segment) -> None:
        """Remove from T1/T2 and add ghost entry to B1/B2.

        This is the ONLY method that mutates T1/T2 for eviction purposes.
        """
        sid = seg.seg_id
        tc = seg.token_count

        if sid in self._t1:
            del self._t1[sid]
            # Add to B1 ghost (evicted from recency list)
            self._b1[sid] = tc
            self._trim_ghost(self._b1)
        elif sid in self._t2:
            del self._t2[sid]
            # Add to B2 ghost (evicted from frequency list)
            self._b2[sid] = tc
            self._trim_ghost(self._b2)

    # ── Core selection ───────────────────────────────────────────────

    def select_evictions(
        self, candidates: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        """Select segments to evict based on ARC ordering.

        READS T1/T2 order without mutation. Uses cand_ids for O(1) lookup.
        Falls back to LRU if internal lists don't cover candidates.
        """
        if not candidates or tokens_to_free <= 0:
            return []

        cand_ids = {s.seg_id for s in candidates}
        cand_map = {s.seg_id: s for s in candidates}

        # Build priority order from T1 and T2 based on adaptive parameter p
        ranked: list[Segment] = []
        t1_tokens = sum(self._t1.values())

        if t1_tokens > self._p:
            # T1 is over target -> evict from T1 first, then T2
            ranked.extend(self._ordered_candidates(self._t1, cand_ids, cand_map))
            ranked.extend(self._ordered_candidates(self._t2, cand_ids, cand_map))
        else:
            # T2 gets priority for eviction, then T1
            ranked.extend(self._ordered_candidates(self._t2, cand_ids, cand_map))
            ranked.extend(self._ordered_candidates(self._t1, cand_ids, cand_map))

        # Fallback: any candidates not in T1/T2 (shouldn't happen, but safety)
        ranked_ids = {s.seg_id for s in ranked}
        for seg in candidates:
            if seg.seg_id not in ranked_ids:
                ranked.append(seg)

        return self._fill_to_budget(ranked, tokens_to_free)

    def _reason(self, seg: Segment) -> str:
        if seg.seg_id in self._t1:
            return "arc:t1"
        if seg.seg_id in self._t2:
            return "arc:t2"
        return "arc:fallback"

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _ordered_candidates(
        lst: OrderedDict[str, int],
        cand_ids: set[str],
        cand_map: dict[str, Segment],
    ) -> list[Segment]:
        """Return candidates present in an ordered list, preserving order (oldest first)."""
        return [cand_map[sid] for sid in lst if sid in cand_ids]

    def _trim_ghost(self, ghost: OrderedDict[str, int]) -> None:
        """Trim a ghost list so total ghost tokens don't exceed capacity."""
        total = sum(ghost.values())
        while total > self._capacity and ghost:
            _, tc = ghost.popitem(last=False)  # Remove oldest
            total -= tc
