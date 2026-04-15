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

import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import structlog

from ctx_rm.core.segment import Segment, Tier

if TYPE_CHECKING:
    from ctx_rm.core.adaptive import AdaptiveWeights
    from ctx_rm.core.feedback import FeedbackTracker
    from ctx_rm.core.graveyard import TieredStore
    from ctx_rm.core.policies.base import EvictionPolicy
    from ctx_rm.core.scorer import Scorer
    from ctx_rm.telemetry.metrics import MetricsCollector

logger = structlog.get_logger()

# Event callback: receives (event_name, data_dict)
EventCallback = Callable[[str, dict[str, Any]], None]


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
        eviction_batch_mode: Literal["fixed", "adaptive"] = "fixed",
        adaptive_single_evict_max_utilization: float = 1.0,
        feedback: FeedbackTracker | None = None,
        adaptive: AdaptiveWeights | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self.token_budget = token_budget
        self.headroom_ratio = headroom_ratio
        self.store = store
        self.policy = policy
        self.scorer = scorer
        self.metrics = metrics
        self.admission_threshold = admission_threshold
        self.eviction_batch_mode = eviction_batch_mode
        self.adaptive_single_evict_max_utilization = adaptive_single_evict_max_utilization
        self.feedback = feedback
        self.adaptive = adaptive
        self._on_event = on_event

        if self.eviction_batch_mode not in {"fixed", "adaptive"}:
            raise ValueError("eviction_batch_mode must be 'fixed' or 'adaptive'")

        # Track segments that have been recalled so we can detect churn.
        self._recalled_ids: set[str] = set()

        # Active context — ordered by insertion (used for rendering to LLM)
        self._active: OrderedDict[str, Segment] = OrderedDict()
        self._active_tokens: int = 0

        # Turn counter
        self._turn: int = 0

        # RLock guards mutation of _active, _active_tokens, _recalled_ids, and
        # _turn. Reentrant so internal helpers like _evict_segment can be
        # invoked from within an already-locked section (e.g., run_eviction_cycle
        # → _evict_segment). Primary mode is single-threaded asyncio, but the
        # lock lets multi-threaded hosts share a bus without data races.
        self._lock = threading.RLock()

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Fire event callback if registered."""
        if self._on_event is not None:
            self._on_event(event, data)

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def active_tokens(self) -> int:
        """Total tokens currently in active context."""
        with self._lock:
            return self._active_tokens

    @property
    def budget_remaining(self) -> int:
        """Tokens available before hitting the budget."""
        with self._lock:
            return self.token_budget - self._active_tokens

    @property
    def headroom_target(self) -> int:
        """Target active token count (budget minus headroom)."""
        return int(self.token_budget * (1 - self.headroom_ratio))

    @property
    def active_segments(self) -> list[Segment]:
        """Snapshot of segments currently in active context (safe to iterate)."""
        with self._lock:
            return list(self._active.values())

    @property
    def turn_number(self) -> int:
        with self._lock:
            return self._turn

    def advance_turn(self, turn_number: int | None = None) -> None:
        """Advance the turn counter.

        Callers typically invoke without arguments; each call increments by 1.
        When `turn_number` is supplied, the counter is set explicitly and the
        call is idempotent: passing the same turn twice is a no-op. This lets
        harnesses that have their own turn tracking stay synchronized without
        double-incrementing on retries.
        """
        with self._lock:
            if turn_number is not None:
                if turn_number == self._turn:
                    return  # Idempotent: same turn twice is a no-op.
                self._turn = turn_number
            else:
                self._turn += 1
            snapshot = {
                "turn_number": self._turn,
                "active_tokens": self._active_tokens,
                "utilization": self._active_tokens / self.token_budget if self.token_budget else 0,
            }
        self._emit("turn_advance", snapshot)

    def ingest(self, segment: Segment) -> None:
        """Add a new segment to active context.

        This is the "bombard" path — the agent ingests freely. If the active
        context exceeds the budget, eviction is triggered automatically.

        Admission control: segments with source 'file_read' or 'tool' whose
        token_count exceeds admission_threshold are routed directly to Warm
        instead of Active, preventing scan pollution.
        """
        with self._lock:
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
                bypass_event = {
                    "seg_id": segment.seg_id,
                    "tokens": segment.token_count,
                    "source": segment.source,
                    "active_tokens": self._active_tokens,
                    "budget": self.token_budget,
                    "bypassed": True,
                }
                self._emit("ingest", bypass_event)
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

            ingest_event = {
                "seg_id": segment.seg_id,
                "tokens": segment.token_count,
                "source": segment.source,
                "active_tokens": self._active_tokens,
                "budget": self.token_budget,
                "bypassed": False,
            }

            over_budget = self._active_tokens > self.headroom_target

        self._emit("ingest", ingest_event)

        if over_budget:
            self.run_eviction_cycle()

    def run_eviction_cycle(self) -> list[Segment]:
        """Score and evict segments until active context is within budget.

        Returns the list of evicted segments for audit/telemetry.
        """
        with self._lock:
            self._refresh_adaptive_policy_params()

            tokens_to_free = self._active_tokens - self.headroom_target
            if tokens_to_free <= 0:
                return []

            if self.eviction_batch_mode == "adaptive":
                evicted = self._run_adaptive_eviction()
            else:
                candidates = self._eviction_candidates()
                if self.scorer:
                    self.scorer.score_batch(candidates, context=list(self._active.values()))
                to_evict = self.policy.select_evictions(candidates, tokens_to_free)
                evicted = []
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

    def _run_adaptive_eviction(self) -> list[Segment]:
        """Adaptive mode: batch when far over budget, otherwise evict one-at-a-time."""
        evicted: list[Segment] = []

        while self._active_tokens > self.headroom_target:
            candidates = self._eviction_candidates()
            if not candidates:
                break

            if self.scorer:
                self.scorer.score_batch(candidates, context=self.active_segments)

            tokens_to_free = self._active_tokens - self.headroom_target
            utilization = self._active_utilization()
            adaptive_single = utilization <= self.adaptive_single_evict_max_utilization

            request_tokens = 1 if adaptive_single else tokens_to_free
            selected = self.policy.select_evictions(candidates, request_tokens)
            if not selected:
                break

            for seg in selected:
                self._evict_segment(seg)
                evicted.append(seg)
                if adaptive_single:
                    break

        return evicted

    def _eviction_candidates(self) -> list[Segment]:
        """Return non-pinned active segments eligible for eviction."""
        return [s for s in self._active.values() if not s.pinned]

    def _active_utilization(self) -> float:
        """Current active token utilization against configured budget."""
        if self.token_budget <= 0:
            return 0.0
        return self._active_tokens / self.token_budget

    def record_eval_result(self, check: str, passed: bool) -> None:
        """Inject external eval outcomes into the feedback/adaptation loop."""
        if self.feedback is not None:
            self.feedback.on_eval_result(check, passed)

    def recall(self, seg_id: str) -> Segment | None:
        """Recall a segment from warm/cold/graveyard back to active (zombie path).

        The primary agent or harness can request specific segments to be
        brought back into active context.
        """
        segment = self.store.recall(seg_id)
        if segment is None:
            logger.warning("recall_miss", seg_id=seg_id)
            return None

        with self._lock:
            segment.recall()
            segment.tier = Tier.ACTIVE
            self._active[segment.seg_id] = segment
            self._active_tokens += segment.token_count
            self._recalled_ids.add(segment.seg_id)

            # Notify policy of access (T1->T2 promotion for ARC, no-op for others)
            self.policy.on_access(segment)

            if self.feedback is not None:
                self.feedback.on_recall(segment)

            if self.metrics:
                self.metrics.record_recall(segment)

            event = {
                "seg_id": segment.seg_id,
                "tokens": segment.token_count,
                "source": segment.source,
                "active_tokens": self._active_tokens,
            }

        logger.info("segment_recalled", seg_id=seg_id, tier_from=segment.tier.value)
        self._emit("recall", event)
        return segment

    def touch_segment(self, seg_id: str) -> bool:
        """Touch an active segment to record access.

        Notifies the policy so stateful policies (e.g., ARC) can track
        recency/frequency transitions.

        Returns True if the segment was found and touched.
        """
        with self._lock:
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
        with self._lock:
            return [
                {"role": seg.role.value, "content": seg.content} for seg in self._active.values()
            ]

    def get_stats(self) -> dict:
        """Return current state statistics for telemetry."""
        with self._lock:
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

        if self.feedback is not None:
            if seg.seg_id in self._recalled_ids:
                self.feedback.on_re_eviction(seg)
                self._recalled_ids.discard(seg.seg_id)
            else:
                self.feedback.on_eviction(seg)

        # Push to warm tier (first stop after eviction)
        self.store.demote_to_warm(seg)

        self._emit(
            "evict",
            {
                "seg_id": seg.seg_id,
                "tokens": seg.token_count,
                "source": seg.source,
                "score": seg.composite_score,
                "active_tokens": self._active_tokens,
            },
        )

    def _refresh_adaptive_policy_params(self) -> None:
        """Update bus-level knobs and policy state from adaptive feedback.

        Three things are reconciled before every eviction cycle:

        1. Recompute feedback statistics (recall rate, source weights).
        2. Apply any headroom adjustment to the bus (clamped to [5%, 50%]).
        3. Forward `eviction_aggressiveness` to the policy so subclasses that
           honor `_fill_to_budget` automatically evict more/less per cycle.
        """
        if self.adaptive is None or self.feedback is None:
            return

        self.adaptive.update_from_feedback(self.feedback)

        maybe_headroom = self.adaptive.policy_params.get("headroom_ratio")
        if maybe_headroom is not None:
            # Keep configured headroom in a safe bounded range.
            self.headroom_ratio = max(0.05, min(0.5, float(maybe_headroom)))

        maybe_aggr = self.adaptive.policy_params.get("eviction_aggressiveness")
        if maybe_aggr is not None:
            self.policy.set_aggressiveness(float(maybe_aggr))
