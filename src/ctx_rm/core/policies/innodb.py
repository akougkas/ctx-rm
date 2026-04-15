"""InnoDB-style split LRU eviction policy.

Implements MySQL InnoDB's buffer pool LRU with midpoint insertion:
  - The LRU list is split into a "new" (young) sublist and an "old" sublist
  - The midpoint is at 3/8 from the tail (old_pct=37 by default)
  - New segments always enter at the head of the OLD sublist
  - Only on re-access (second touch) does a segment promote from old to new
  - Eviction prefers the old sublist tail, then falls back to new sublist tail

This design prevents "scan pollution" — large sequential reads (file_read, tool
output) enter the old sublist and get evicted quickly unless the agent actually
re-accesses them. Needle content that gets re-accessed promotes to the new
sublist and is protected from eviction.

Key properties:
  - _new: segments accessed more than once (protected, young sublist)
  - _old: segments accessed only once or recently ingested (old sublist)
  - Midpoint insertion at old_pct (default 37% = ~3/8)
  - Eviction order: old tail first, then new tail
"""

from __future__ import annotations

from collections import OrderedDict

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment


class InnoDBPolicy(EvictionPolicy):
    """InnoDB buffer pool split LRU eviction policy.

    Maintains new (young) and old sublists with midpoint insertion.
    New segments enter the old sublist tail. On re-access, segments
    promote from old to new. Eviction prefers old sublist tail.
    """

    def __init__(self, capacity_tokens: int, old_pct: int = 37) -> None:
        self._capacity = capacity_tokens
        self._old_pct = old_pct

        # New sublist: segments that have been re-accessed (protected)
        # Old sublist: segments accessed only once (insertion point)
        # OrderedDict: oldest at front (popitem(last=False)), newest at end
        self._new: OrderedDict[str, int] = OrderedDict()  # seg_id -> token_count
        self._old: OrderedDict[str, int] = OrderedDict()  # seg_id -> token_count

        self._new_tokens: int = 0
        self._old_tokens: int = 0
        self._old_max_tokens: int = int(capacity_tokens * old_pct / 100)

    @property
    def name(self) -> str:
        return "innodb"

    # -- Lifecycle hooks -------------------------------------------------------

    def on_ingest(self, seg: Segment) -> None:
        """New segments always enter the old sublist (midpoint insertion)."""
        sid = seg.seg_id
        tc = seg.token_count

        # Skip if already tracked
        if sid in self._new or sid in self._old:
            return

        if isinstance(seg.metadata.get("reingest_evicted_seg_id"), str):
            self._new[sid] = tc
            self._new_tokens += tc
            return

        # Insert at end of old sublist (tail = most recent insertion)
        self._old[sid] = tc
        self._old_tokens += tc

    def on_access(self, seg: Segment) -> None:
        """Re-access promotes old->new, or refreshes position within new."""
        sid = seg.seg_id

        if sid in self._old:
            # Second touch: promote from old to new (young) sublist
            tc = self._old.pop(sid)
            self._old_tokens -= tc
            self._new[sid] = tc
            self._new_tokens += tc
        elif sid in self._new:
            # Already in new sublist: refresh position (move to end = most recent)
            self._new.move_to_end(sid)

    def on_evict(self, seg: Segment) -> None:
        """Remove from whichever sublist the segment lives in."""
        sid = seg.seg_id

        if sid in self._old:
            tc = self._old.pop(sid)
            self._old_tokens -= tc
        elif sid in self._new:
            tc = self._new.pop(sid)
            self._new_tokens -= tc

    # -- Core selection --------------------------------------------------------

    def select_evictions(
        self, candidates: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        """Select segments to evict: prefer old sublist tail, then new sublist tail.

        READ-ONLY on _old/_new. Does NOT call on_evict. The caller (ContextBus)
        is responsible for calling on_evict after actual eviction.
        """
        if not candidates or tokens_to_free <= 0:
            return []

        cand_ids = {s.seg_id for s in candidates}
        cand_map = {s.seg_id: s for s in candidates}

        ranked: list[Segment] = []

        # 1. Old sublist candidates (oldest first = front of OrderedDict)
        for sid in self._old:
            if sid in cand_ids:
                ranked.append(cand_map[sid])

        # 2. New sublist candidates (oldest first = front of OrderedDict)
        for sid in self._new:
            if sid in cand_ids:
                ranked.append(cand_map[sid])

        # 3. Fallback: any candidates not in either sublist (shouldn't happen)
        ranked_ids = {s.seg_id for s in ranked}
        for seg in sorted(candidates, key=lambda s: s.last_accessed):
            if seg.seg_id not in ranked_ids:
                ranked.append(seg)

        return self._fill_to_budget(ranked, tokens_to_free)

    def _reason(self, seg: Segment) -> str:
        if seg.seg_id in self._old:
            return "innodb:old"
        if seg.seg_id in self._new:
            return "innodb:new"
        return "innodb:fallback"
