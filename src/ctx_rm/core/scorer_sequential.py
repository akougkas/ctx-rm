"""SequentialScorer: task-aware conditional scoring with pluggable LLM callable.

Scores each candidate segment against the current retained context and task goal.
Uses a pluggable scoring callable for LLM-based evaluation, with automatic
fallback to HeuristicScorer on failure. Results are cached by
(segment_hash, retained_set_hash, task_hash) to avoid redundant scoring.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from typing import TYPE_CHECKING, Callable

import structlog

from ctx_rm.core.scorer import HeuristicScorer, Scorer
from ctx_rm.core.segment import Segment

if TYPE_CHECKING:
    from ctx_rm.core.adaptive import AdaptiveWeights

logger = structlog.get_logger()

# Maximum characters per segment in the retained-set summary
_SUMMARY_SEGMENT_LIMIT = 200
# Maximum total characters for the retained-set summary
_SUMMARY_TOTAL_LIMIT = 2000

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{3,}")
_STOP_WORDS = frozenset(
    {
        "and",
        "are",
        "for",
        "from",
        "has",
        "have",
        "into",
        "that",
        "the",
        "this",
        "with",
        "you",
    }
)


def summarize_retained_set(
    segments: list[Segment], *, max_total: int = _SUMMARY_TOTAL_LIMIT
) -> str:
    """Build a deterministic, token-safe summary of retained segments.

    Each segment is truncated to _SUMMARY_SEGMENT_LIMIT chars. The overall
    summary is truncated to *max_total* chars. Segments are processed in
    list order (typically ingestion order) for determinism.
    """
    parts: list[str] = []
    total = 0
    for seg in segments:
        snippet = seg.content[:_SUMMARY_SEGMENT_LIMIT]
        if len(seg.content) > _SUMMARY_SEGMENT_LIMIT:
            snippet += "..."
        line = f"[{seg.role.value}] {snippet}"
        if total + len(line) > max_total:
            remaining = max_total - total
            if remaining > 10:
                parts.append(line[:remaining] + "...")
            break
        parts.append(line)
        total += len(line) + 1  # +1 for newline
    return "\n".join(parts)


def _hash(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _keywords(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOP_WORDS}


def _overlap_ratio(candidate_terms: set[str], reference_terms: set[str]) -> float:
    if not reference_terms:
        return 0.0
    return len(candidate_terms & reference_terms) / len(reference_terms)


# Type alias for the scoring callable.
# It receives (segment_content, retained_summary, task_goal) and returns a dict
# with keys: relevance_score, staleness_score, redundancy_score, composite_score.
# All values should be floats in [0, 1].
ScoringCallable = Callable[[str, str, str], dict[str, float] | None]


class SequentialScorer(Scorer):
    """Task-aware sequential scorer with pluggable LLM callable.

    For each candidate segment, builds a retained-context summary and
    invokes *scoring_fn(segment_content, retained_summary, task_goal)*.
    If no scoring_fn is supplied, a built-in conditional lexical backend is
    used so sequential scoring remains active in production wiring.

    Failure handling has three layers:
      1. Per-call failures are logged at WARNING level (not DEBUG) and fall
         back to HeuristicScorer for the failing segments only.
      2. A circuit breaker trips after *failure_threshold* consecutive
         failures from the external scoring callable; while tripped, the
         scorer uses the HeuristicScorer fallback and skips the expensive
         LLM path entirely. It resets on the next successful call or after
         *breaker_cooldown_seconds*, whichever comes first.
      3. Failure counters are exposed via get_stats() so operators can
         detect silent degradation without reading logs.

    Results are cached by (segment_hash, retained_set_hash, task_hash)
    so repeated scoring of the same segment in the same context is free.
    The cache is bounded by *max_cache_entries* and uses LRU eviction.
    """

    _REQUIRED_KEYS = frozenset(
        {"relevance_score", "staleness_score", "redundancy_score", "composite_score"}
    )

    def __init__(
        self,
        scoring_fn: ScoringCallable | None = None,
        task_goal: str = "",
        fallback: Scorer | None = None,
        max_cache_entries: int = 4096,
        adaptive: AdaptiveWeights | None = None,
        failure_threshold: int = 5,
        breaker_cooldown_seconds: float = 60.0,
    ) -> None:
        self._scoring_fn = scoring_fn
        self._task_goal = task_goal
        self._fallback = fallback or HeuristicScorer()
        self._max_cache_entries = max_cache_entries
        self._cache: OrderedDict[tuple[str, str, str], dict[str, float]] = OrderedDict()
        self._adaptive = adaptive

        # Circuit breaker state
        self._failure_threshold = max(1, failure_threshold)
        self._breaker_cooldown_seconds = breaker_cooldown_seconds
        self._consecutive_failures: int = 0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._breaker_tripped_at: float | None = None

    def score_batch(self, candidates: list[Segment], context: list[Segment]) -> None:
        """Score candidates sequentially against retained context.

        Sets relevance_score, staleness_score, redundancy_score, and
        composite_score on each segment in-place.

        The external scoring callable is skipped entirely when the circuit
        breaker is tripped, routing the full batch through the heuristic
        fallback until the breaker resets.
        """
        # Short-circuit when no external backend is configured — no breaker needed
        # because the lexical default can never raise.
        if self._scoring_fn is None:
            self._score_with_callable(candidates, context, self._default_scoring_fn)
            return

        # Breaker open: skip the LLM entirely and serve everything from fallback.
        if self._is_breaker_open():
            logger.info(
                "sequential_scorer_breaker_open",
                consecutive_failures=self._consecutive_failures,
                total_failures=self._total_failures,
            )
            self._fallback.score_batch(candidates, context)
            for seg in candidates:
                self._apply_adaptive(seg)
            return

        self._score_with_callable(candidates, context, self._scoring_fn)

    def _score_with_callable(
        self,
        candidates: list[Segment],
        context: list[Segment],
        scoring_fn: ScoringCallable,
    ) -> None:
        task_hash = _hash(self._task_goal)
        failed: list[Segment] = []

        for seg in candidates:
            # Exclude the candidate itself when computing retained-set context.
            # ContextBus passes active segments as both candidates and context,
            # so this preserves proper marginal-value semantics.
            retained_segments = [s for s in context if s.seg_id != seg.seg_id]
            retained_summary = summarize_retained_set(retained_segments)
            retained_hash = _hash(retained_summary)
            seg_hash = _hash(seg.content)
            cache_key = (seg_hash, retained_hash, task_hash)

            if cache_key in self._cache:
                scores = self._cache[cache_key]
                self._cache.move_to_end(cache_key)
                self._apply_scores(seg, scores)
                self._apply_adaptive(seg)
                continue

            try:
                result = scoring_fn(seg.content, retained_summary, self._task_goal)
                if not self._validate_result(result):
                    logger.warning(
                        "sequential_scorer_invalid_result",
                        seg_id=seg.seg_id,
                        result_type=type(result).__name__,
                    )
                    self._register_failure()
                    failed.append(seg)
                    continue

                scores = {k: max(0.0, min(1.0, float(result[k]))) for k in self._REQUIRED_KEYS}
                self._cache_set(cache_key, scores)
                self._apply_scores(seg, scores)
                self._apply_adaptive(seg)
                self._register_success()

            except Exception as e:
                logger.warning(
                    "sequential_scorer_error",
                    seg_id=seg.seg_id,
                    error=str(e),
                )
                self._register_failure()
                failed.append(seg)

            # If the breaker tripped mid-batch, stop calling the external fn
            # and route the rest of the batch through fallback.
            if self._is_breaker_open():
                already_scored_ids = {s.seg_id for s in candidates[: candidates.index(seg) + 1]}
                tail = [s for s in candidates if s.seg_id not in already_scored_ids]
                if tail:
                    self._fallback.score_batch(tail, context)
                    for tail_seg in tail:
                        self._apply_adaptive(tail_seg)
                break

        if failed:
            self._fallback.score_batch(failed, context)
            for seg in failed:
                self._apply_adaptive(seg)

    def _register_failure(self) -> None:
        import time as _time

        self._consecutive_failures += 1
        self._total_failures += 1
        if (
            self._consecutive_failures >= self._failure_threshold
            and self._breaker_tripped_at is None
        ):
            self._breaker_tripped_at = _time.time()
            logger.error(
                "sequential_scorer_breaker_tripped",
                consecutive_failures=self._consecutive_failures,
                threshold=self._failure_threshold,
                cooldown_seconds=self._breaker_cooldown_seconds,
            )

    def _register_success(self) -> None:
        self._consecutive_failures = 0
        self._total_successes += 1
        if self._breaker_tripped_at is not None:
            logger.info("sequential_scorer_breaker_reset_on_success")
            self._breaker_tripped_at = None

    def _is_breaker_open(self) -> bool:
        import time as _time

        if self._breaker_tripped_at is None:
            return False
        if _time.time() - self._breaker_tripped_at >= self._breaker_cooldown_seconds:
            logger.info("sequential_scorer_breaker_cooldown_elapsed")
            self._breaker_tripped_at = None
            self._consecutive_failures = 0
            return False
        return True

    def get_stats(self) -> dict[str, int | bool | float]:
        """Return counters and breaker state for observability."""
        return {
            "consecutive_failures": self._consecutive_failures,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "breaker_open": self._is_breaker_open(),
            "cache_entries": len(self._cache),
        }

    def _validate_result(self, result: object) -> bool:
        """Check that result is a dict with all required score keys and valid values."""
        if not isinstance(result, dict):
            return False
        if not self._REQUIRED_KEYS.issubset(result.keys()):
            return False
        for key in self._REQUIRED_KEYS:
            val = result[key]
            if not isinstance(val, (int, float)):
                return False
        return True

    def _cache_set(self, key: tuple[str, str, str], value: dict[str, float]) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        # Bound cache growth for long-running sessions and benchmark sweeps.
        if len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)

    @staticmethod
    def _apply_scores(seg: Segment, scores: dict[str, float]) -> None:
        seg.relevance_score = scores["relevance_score"]
        seg.staleness_score = scores["staleness_score"]
        seg.redundancy_score = scores["redundancy_score"]
        seg.composite_score = scores["composite_score"]

    def _apply_adaptive(self, seg: Segment) -> None:
        """Apply adaptive overlays to composite score when configured."""
        if self._adaptive is None or seg.composite_score is None:
            return
        seg.composite_score = self._adaptive.apply_to_composite(
            seg.composite_score,
            seg.source,
            seg.seg_id,
        )

    @staticmethod
    def _default_scoring_fn(
        segment_content: str,
        retained_summary: str,
        task_goal: str,
    ) -> dict[str, float]:
        """Default conditional backend used when no external LLM scorer is supplied.

        This backend approximates task-conditioned marginal value with lexical
        signals so `--scorer sequential` is functional out-of-the-box:
          - relevance: overlap with task goal terms
          - redundancy: overlap with retained-set terms
          - staleness: neutral value (no recency clock in this interface)
        """
        seg_terms = _keywords(segment_content)
        task_terms = _keywords(task_goal)
        retained_terms = _keywords(retained_summary)

        relevance = _overlap_ratio(seg_terms, task_terms) if task_terms else 0.5
        redundancy = _overlap_ratio(seg_terms, retained_terms)
        staleness = 0.5

        composite = _clamp(0.6 * relevance + 0.3 * (1.0 - redundancy) + 0.1 * staleness)

        return {
            "relevance_score": _clamp(relevance),
            "staleness_score": staleness,
            "redundancy_score": _clamp(redundancy),
            "composite_score": composite,
        }
