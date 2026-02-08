"""SequentialScorer: task-aware conditional scoring with pluggable LLM callable.

Scores each candidate segment against the current retained context and task goal.
Uses a pluggable scoring callable for LLM-based evaluation, with automatic
fallback to HeuristicScorer on failure. Results are cached by
(segment_hash, retained_set_hash, task_hash) to avoid redundant scoring.
"""

from __future__ import annotations

import hashlib
from typing import Callable

import structlog

from ctx_rm.core.scorer import HeuristicScorer, Scorer
from ctx_rm.core.segment import Segment

logger = structlog.get_logger()

# Maximum characters per segment in the retained-set summary
_SUMMARY_SEGMENT_LIMIT = 200
# Maximum total characters for the retained-set summary
_SUMMARY_TOTAL_LIMIT = 2000


def summarize_retained_set(segments: list[Segment], *, max_total: int = _SUMMARY_TOTAL_LIMIT) -> str:
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


# Type alias for the scoring callable.
# It receives (segment_content, retained_summary, task_goal) and returns a dict
# with keys: relevance_score, staleness_score, redundancy_score, composite_score.
# All values should be floats in [0, 1].
ScoringCallable = Callable[[str, str, str], dict[str, float]]


class SequentialScorer(Scorer):
    """Task-aware sequential scorer with pluggable LLM callable.

    For each candidate segment, builds a retained-context summary and
    invokes *scoring_fn(segment_content, retained_summary, task_goal)*.
    The callable should return a dict with score fields. On any failure
    or invalid return, falls back to HeuristicScorer.

    Results are cached by (segment_hash, retained_set_hash, task_hash)
    so repeated scoring of the same segment in the same context is free.
    """

    _REQUIRED_KEYS = frozenset(
        {"relevance_score", "staleness_score", "redundancy_score", "composite_score"}
    )

    def __init__(
        self,
        scoring_fn: ScoringCallable | None = None,
        task_goal: str = "",
        fallback: Scorer | None = None,
    ) -> None:
        self._scoring_fn = scoring_fn
        self._task_goal = task_goal
        self._fallback = fallback or HeuristicScorer()
        self._cache: dict[tuple[str, str, str], dict[str, float]] = {}

    def score_batch(
        self, candidates: list[Segment], context: list[Segment]
    ) -> None:
        """Score candidates sequentially against retained context.

        Sets relevance_score, staleness_score, redundancy_score, and
        composite_score on each segment in-place.
        """
        if self._scoring_fn is None:
            self._fallback.score_batch(candidates, context)
            return

        retained_summary = summarize_retained_set(context)
        retained_hash = _hash(retained_summary)
        task_hash = _hash(self._task_goal)

        failed: list[Segment] = []

        for seg in candidates:
            seg_hash = _hash(seg.content)
            cache_key = (seg_hash, retained_hash, task_hash)

            if cache_key in self._cache:
                scores = self._cache[cache_key]
                self._apply_scores(seg, scores)
                continue

            try:
                result = self._scoring_fn(seg.content, retained_summary, self._task_goal)
                if not self._validate_result(result):
                    logger.debug(
                        "sequential_scorer_invalid_result",
                        seg_id=seg.seg_id,
                    )
                    failed.append(seg)
                    continue

                scores = {k: max(0.0, min(1.0, float(result[k]))) for k in self._REQUIRED_KEYS}
                self._cache[cache_key] = scores
                self._apply_scores(seg, scores)

            except Exception as e:
                logger.debug(
                    "sequential_scorer_error",
                    seg_id=seg.seg_id,
                    error=str(e),
                )
                failed.append(seg)

        if failed:
            self._fallback.score_batch(failed, context)

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

    @staticmethod
    def _apply_scores(seg: Segment, scores: dict[str, float]) -> None:
        seg.relevance_score = scores["relevance_score"]
        seg.staleness_score = scores["staleness_score"]
        seg.redundancy_score = scores["redundancy_score"]
        seg.composite_score = scores["composite_score"]
