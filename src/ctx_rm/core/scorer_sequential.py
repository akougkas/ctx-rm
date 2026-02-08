"""SequentialScorer: task-aware conditional scoring with pluggable LLM callable.

Scores each candidate segment against the current retained context and task goal.
Uses a pluggable scoring callable for LLM-based evaluation, with automatic
fallback to HeuristicScorer on failure. Results are cached by
(segment_hash, retained_set_hash, task_hash) to avoid redundant scoring.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable

import structlog

from ctx_rm.core.scorer import HeuristicScorer, Scorer
from ctx_rm.core.segment import Segment

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


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _keywords(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOP_WORDS
    }


def _overlap_ratio(candidate_terms: set[str], reference_terms: set[str]) -> float:
    if not reference_terms:
        return 0.0
    return len(candidate_terms & reference_terms) / len(reference_terms)


# Type alias for the scoring callable.
# It receives (segment_content, retained_summary, task_goal) and returns a dict
# with keys: relevance_score, staleness_score, redundancy_score, composite_score.
# All values should be floats in [0, 1].
ScoringCallable = Callable[[str, str, str], dict[str, float]]


class SequentialScorer(Scorer):
    """Task-aware sequential scorer with pluggable LLM callable.

    For each candidate segment, builds a retained-context summary and
    invokes *scoring_fn(segment_content, retained_summary, task_goal)*.
    If no scoring_fn is supplied, a built-in conditional lexical backend is
    used so sequential scoring remains active in production wiring.
    On any failure or invalid return, falls back to HeuristicScorer.

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
        scoring_fn = self._scoring_fn or self._default_scoring_fn

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
                self._apply_scores(seg, scores)
                continue

            try:
                result = scoring_fn(seg.content, retained_summary, self._task_goal)
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

        composite = _clamp(
            0.6 * relevance
            + 0.3 * (1.0 - redundancy)
            + 0.1 * staleness
        )

        return {
            "relevance_score": _clamp(relevance),
            "staleness_score": staleness,
            "redundancy_score": _clamp(redundancy),
            "composite_score": composite,
        }
