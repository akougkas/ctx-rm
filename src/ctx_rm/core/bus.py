"""ContextBus: the central coordinator for context segments.

The bus is the integration point between the primary agent's context and
ctx-rm's tiered eviction system. It tracks all segments, delegates to the
TieredStore for tier transitions, and provides the API for:
  - Ingesting new segments
  - Querying active context (what gets sent to the LLM)
  - Triggering eviction cycles
  - Recalling segments from cold storage (zombie path)
  - Token budget enforcement
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

import structlog

from ctx_rm.core.segment import Segment, Tier

if TYPE_CHECKING:
    from ctx_rm.core.graveyard import TieredStore
    from ctx_rm.core.policies.base import EvictionPolicy
    from ctx_rm.core.scorer import Scorer
    from ctx_rm.telemetry.metrics import MetricsCollector

logger = structlog.get_logger()


class ContextBus:
    """Central coordinator for context removal.

    Manages the flow of segments across tiers and enforces token budgets.
    Designed to sit between the benchmark harness and the CLI agent drivers.
    """

    def __init__(
        self,
        token_budget: int,
        store: TieredStore,
        policy: EvictionPolicy,
        scorer: Scorer | None = None,
        metrics: MetricsCollector | None = None,
        headroom_ratio: float = 0.15,  # Keep 15% headroom by default
        admission_threshold: int = 2000,
    ) -> None:
        self.token_budget = token_budget
        self.headroom_ratio = headroom_ratio
        self.store = store
        self.policy = policy
        self.scorer = scorer
        self.metrics = metrics
        self.admission_threshold = admission_threshold

        # Active context — ordered by insertion (used for rendering to LLM)
        self._active: OrderedDict[str, Segment] = OrderedDict()
        self._active_tokens: int = 0

        # Turn counter
        self._turn: int = 0

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def active_tokens(self) -> int:
        """Total tokens currently in active context."""
        return self._active_tokens

    @property
    def budget_remaining(self) -> int:
        """Tokens available before hitting the budget."""
        return self.token_budget - self._active_tokens

    @property
    def headroom_target(self) -> int:
        """Target active token count (budget minus headroom)."""
        return int(self.token_budget * (1 - self.headroom_ratio))

    @property
    def active_segments(self) -> list[Segment]:
        """Ordered list of segments currently in active context."""
        return list(self._active.values())

    @property
    def turn_number(self) -> int:
        return self._turn

    def advance_turn(self) -> None:
        """Advance the turn counter — called by the harness between agent turns."""
        self._turn += 1

    def ingest(self, segment: Segment) -> None:
        """Add a new segment to active context.

        This is the "bombard" path — the agent ingests freely. If the active
        context exceeds the budget, eviction is triggered automatically.

        Admission control: segments with source 'file_read' or 'tool' whose
        token_count exceeds admission_threshold are routed directly to Warm
        instead of Active, preventing scan pollution.
        """
        segment.turn_number = self._turn

        # Admission control: route large file_read/tool segments to Warm
        if self._should_bypass_active(segment):
            segment.tier = Tier.WARM
            self.store.demote_to_warm(segment)
            logger.debug(
                "segment_admitted_to_warm",
                seg_id=segment.seg_id,
                tokens=segment.token_count,
                source=segment.source,
            )
            if self.metrics:
                self.metrics.record_ingest(segment)
            return

        segment.tier = Tier.ACTIVE
        self._active[segment.seg_id] = segment
        self._active_tokens += segment.token_count

        # Notify policy of ingest (ghost hit detection for ARC, no-op for others)
        self.policy.on_ingest(segment)

        if self.metrics:
            self.metrics.record_ingest(segment)

        logger.debug(
            "segment_ingested",
            seg_id=segment.seg_id,
            tokens=segment.token_count,
            active_total=self._active_tokens,
            budget=self.token_budget,
        )

        # Auto-evict if over budget
        if self._active_tokens > self.headroom_target:
            self.run_eviction_cycle()

    def run_eviction_cycle(self) -> list[Segment]:
        """Score and evict segments until active context is within budget.

        Returns the list of evicted segments for audit/telemetry.
        """
        # Score all non-pinned active segments
        candidates = [s for s in self._active.values() if not s.pinned]

        if self.scorer:
            self.scorer.score_batch(candidates, context=self.active_segments)

        # Ask the policy which segments to evict
        tokens_to_free = self._active_tokens - self.headroom_target
        if tokens_to_free <= 0:
            return []

        to_evict = self.policy.select_evictions(candidates, tokens_to_free)
        evicted: list[Segment] = []

        for seg in to_evict:
            self._evict_segment(seg)
            evicted.append(seg)

        if self.metrics:
            self.metrics.record_eviction_cycle(evicted, self._active_tokens)

        logger.info(
            "eviction_cycle_complete",
            evicted_count=len(evicted),
            evicted_tokens=sum(s.token_count for s in evicted),
            active_tokens=self._active_tokens,
        )

        return evicted

    def recall(self, seg_id: str) -> Segment | None:
        """Recall a segment from warm/cold/graveyard back to active (zombie path).

        The primary agent or harness can request specific segments to be
        brought back into active context.
        """
        segment = self.store.recall(seg_id)
        if segment is None:
            logger.warning("recall_miss", seg_id=seg_id)
            return None

        segment.recall()
        segment.tier = Tier.ACTIVE
        self._active[segment.seg_id] = segment
        self._active_tokens += segment.token_count

        # Notify policy of access (T1->T2 promotion for ARC, no-op for others)
        self.policy.on_access(segment)

        if self.metrics:
            self.metrics.record_recall(segment)

        logger.info("segment_recalled", seg_id=seg_id, tier_from=segment.tier.value)
        return segment

    def touch_segment(self, seg_id: str) -> bool:
        """Touch an active segment to record access.

        Notifies the policy so stateful policies (e.g., ARC) can track
        recency/frequency transitions.

        Returns True if the segment was found and touched.
        """
        seg = self._active.get(seg_id)
        if seg is None:
            return False
        seg.touch()
        self.policy.on_access(seg)
        return True

    def search_graveyard(self, query: str, top_k: int = 5) -> list[Segment]:
        """Search evicted segments in cold storage by content similarity."""
        return self.store.search(query, top_k=top_k)

    def search_evicted(self, query: str, top_k: int = 5) -> list[Segment]:
        """Search all evicted segments (warm + cold) by content match."""
        return self.store.search_all(query, top_k=top_k)

    def render_context(self) -> list[dict[str, str]]:
        """Render active context as a list of role/content pairs.

        This is what gets passed to the CLI agent in each turn.
        """
        return [
            {"role": seg.role.value, "content": seg.content}
            for seg in self._active.values()
        ]

    def get_stats(self) -> dict:
        """Return current state statistics for telemetry."""
        return {
            "turn": self._turn,
            "active_segments": len(self._active),
            "active_tokens": self._active_tokens,
            "budget": self.token_budget,
            "headroom_target": self.headroom_target,
            "utilization": self._active_tokens / self.token_budget if self.token_budget else 0,
            "store_stats": self.store.get_stats(),
        }

    # ── Internal ────────────────────────────────────────────────────────

    # Sources that trigger admission control bypass
    _ADMISSION_SOURCES = frozenset({"file_read", "tool"})

    def _should_bypass_active(self, segment: Segment) -> bool:
        """Check if a segment should bypass Active and go directly to Warm.

        Large segments from file_read or tool sources are routed to Warm to
        prevent scan pollution in the active context.
        """
        if segment.source is None:
            return False
        # Match source prefix (e.g., "file_read:src/auth.py" or "tool:bash")
        source_prefix = segment.source.split(":")[0] if ":" in segment.source else segment.source
        return (
            source_prefix in self._ADMISSION_SOURCES
            and segment.token_count > self.admission_threshold
        )

    def _evict_segment(self, seg: Segment) -> None:
        """Remove a segment from active and push to tiered store."""
        # Notify policy of eviction (ghost list update for ARC, no-op for others)
        self.policy.on_evict(seg)

        if seg.seg_id in self._active:
            del self._active[seg.seg_id]
            self._active_tokens -= seg.token_count

        # Push to warm tier (first stop after eviction)
        self.store.demote_to_warm(seg)
