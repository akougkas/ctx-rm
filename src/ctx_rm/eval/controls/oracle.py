"""OraclePolicy: evicts using perfect foresight of future references.

The oracle is the *upper bound* for any real policy on a given trace. It
cheats by reading the precomputed reference graph: a segment is safe to
evict iff no later segment references it at any future turn. If multiple
segments are safe, the oracle picks the ones whose next reference (if any)
is furthest in the future, i.e. it protects the soonest-needed items first.

This is deliberately simple. The paper's claim is "real policies fall
between OraclePolicy and RandomPolicy on our corpus"; we don't need an
optimal Belady simulator to make that argument, just a tight upper bound.

Semantics vs `EvictionPolicy` base
----------------------------------
OraclePolicy subclasses `EvictionPolicy` so the L1 runner can drive it with
the same code path as any real policy. The `set_current_turn` method is how
the runner informs the policy about the logical boundary between "past" and
"future" as the replay progresses. Without that call, the policy degrades
to LRU.
"""

from __future__ import annotations

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment
from ctx_rm.eval.trace.reference_graph import ReferenceGraph


class OraclePolicy(EvictionPolicy):
    """Future-aware eviction. Never touches referenced-later segments."""

    def __init__(self, graph: ReferenceGraph) -> None:
        self._graph = graph
        self._current_turn: int = 0

    @property
    def name(self) -> str:
        return "oracle"

    def set_current_turn(self, turn: int) -> None:
        self._current_turn = turn

    def select_evictions(self, candidates: list[Segment], tokens_to_free: int) -> list[Segment]:
        if not candidates or tokens_to_free <= 0:
            return []

        # Partition by "will be referenced after this turn".
        safe: list[Segment] = []  # Not referenced again — free to evict.
        needed: list[tuple[int, Segment]] = []  # Referenced; sort by distance.
        for seg in candidates:
            # Prefer the graph's labels. Missing labels => assume needed.
            earliest = self._graph.earliest_future_turn(seg.seg_id)
            if earliest is None or earliest <= self._current_turn:
                safe.append(seg)
            else:
                needed.append((earliest, seg))

        # Safe segments go first, oldest first so we keep tiebreak stable.
        safe.sort(key=lambda s: s.last_accessed)

        # If we must evict referenced segments to hit the free target, pick
        # the ones whose next reference is furthest away — they have the
        # most slack before needing a recall.
        needed.sort(key=lambda pair: -pair[0])
        ranked = safe + [s for _, s in needed]

        return self._fill_to_budget(ranked, tokens_to_free)

    def _reason(self, seg: Segment) -> str:
        earliest = self._graph.earliest_future_turn(seg.seg_id)
        if earliest is None or earliest <= self._current_turn:
            return "oracle:unreferenced"
        return f"oracle:next_ref_turn={earliest}"
