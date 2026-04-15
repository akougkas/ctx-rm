"""Scorer: evaluates the value of each segment for eviction decisions.

The Scorer is pluggable — start with fast heuristics, optionally add
LLM-based scoring later. All scorers produce a composite_score in [0, 1]
where 0 = low value (evict first) and 1 = high value (keep).
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod

from ctx_rm.core.segment import Segment

_SHINGLE_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_SHINGLE_SIZE = 5


def _compute_shingles(content: str) -> frozenset[int]:
    """Hashed k-shingle set for redundancy detection.

    Uses 5-token shingles so paraphrase near-duplicates still overlap and
    byte-identical reads yield Jaccard 1.0. Empty content produces an
    empty set, which _jaccard treats as no overlap.
    """
    tokens = _SHINGLE_TOKEN_RE.findall(content.lower())
    if len(tokens) < _SHINGLE_SIZE:
        return frozenset(hash(tok) for tok in tokens)
    return frozenset(
        hash(tuple(tokens[i : i + _SHINGLE_SIZE])) for i in range(len(tokens) - _SHINGLE_SIZE + 1)
    )


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


class Scorer(ABC):
    """Base protocol for context scorers."""

    @abstractmethod
    def score_batch(self, candidates: list[Segment], context: list[Segment]) -> None:
        """Score a batch of candidate segments in-place.

        Sets `relevance_score`, `staleness_score`, `redundancy_score`,
        and `composite_score` on each segment.

        Args:
            candidates: Segments to score.
            context: Full active context (for relative scoring).
        """


class HeuristicScorer(Scorer):
    """Fast heuristic scorer — no LLM calls.

    Combines up to four signals:
      - Recency: exponential decay based on idle time
      - Frequency: log-scaled access count
      - Role weight: system > user > assistant > tool (configurable)
      - Source weight: needle > user_task > noise (opt-in, default 0)

    When source_weight=0 (default), behavior is identical to the original
    three-signal scorer. When source_weight > 0, the source prefix (e.g.,
    "needle", "noise") influences the composite score, allowing the eviction
    engine to prefer keeping needles over noise.
    """

    def __init__(
        self,
        recency_halflife: float = 300.0,  # 5 minutes
        frequency_weight: float = 0.2,
        recency_weight: float = 0.5,
        role_weight: float = 0.3,
        source_weight: float = 0.0,
        redundancy_weight: float = 0.15,
        role_scores: dict[str, float] | None = None,
        source_scores: dict[str, float] | None = None,
    ) -> None:
        self.recency_halflife = recency_halflife
        self.w_freq = frequency_weight
        self.w_rec = recency_weight
        self.w_role = role_weight
        self.w_source = source_weight
        self.w_redundancy = redundancy_weight

        self.role_scores = role_scores or {
            "system": 1.0,
            "user": 0.8,
            "assistant": 0.5,
            "tool": 0.3,
        }

        self.source_scores = source_scores or {
            "system_prompt": 1.0,
            "user_task": 0.9,
            "needle": 0.85,
            "assistant_response": 0.6,
            "assistant_tool_call": 0.5,
            "tool": 0.4,
            "noise": 0.1,
        }

    def score_batch(self, candidates: list[Segment], context: list[Segment]) -> None:
        # Tokenize each unique segment once per batch. Candidates and context
        # often overlap, so we key by seg_id to avoid double work on large runs.
        shingle_cache: dict[str, frozenset[int]] = {}
        for seg in context:
            if seg.seg_id not in shingle_cache and seg.content:
                shingle_cache[seg.seg_id] = _compute_shingles(seg.content)
        for seg in candidates:
            if seg.seg_id not in shingle_cache and seg.content:
                shingle_cache[seg.seg_id] = _compute_shingles(seg.content)

        context_ids = [s.seg_id for s in context]

        for seg in candidates:
            seg.staleness_score = self._recency_score(seg)
            seg.relevance_score = self._frequency_score(seg)
            seg.redundancy_score = self._redundancy_score(seg, shingle_cache, context_ids)
            role_score = self.role_scores.get(seg.role.value, 0.5)

            base = (
                self.w_rec * seg.staleness_score
                + self.w_freq * seg.relevance_score
                + self.w_role * role_score
            )

            # Redundancy penalty: duplicate content subtracts value.
            base -= self.w_redundancy * seg.redundancy_score

            if self.w_source > 0:
                source_score = self._source_score(seg)
                seg.composite_score = base * (1 - self.w_source) + source_score * self.w_source
            else:
                seg.composite_score = base

            # Clamp composite to [0, 1] in case redundancy pushes it negative.
            if seg.composite_score < 0:
                seg.composite_score = 0.0
            elif seg.composite_score > 1:
                seg.composite_score = 1.0

    def _recency_score(self, seg: Segment) -> float:
        """Exponential decay: score = 2^(-idle / halflife)."""
        return math.pow(2, -seg.idle_seconds / self.recency_halflife)

    def _frequency_score(self, seg: Segment) -> float:
        """Log-scaled frequency: score = log2(1 + access_count) / 10, capped at 1."""
        return min(1.0, math.log2(1 + seg.access_count) / 10)

    def _redundancy_score(
        self,
        seg: Segment,
        shingle_cache: dict[str, frozenset[int]],
        context_ids: list[str],
    ) -> float:
        """Max Jaccard overlap against any other segment in the context.

        Uses 5-token shingle sets so paraphrase near-duplicates still register,
        not just byte-identical reads. Excludes the candidate itself.
        """
        own = shingle_cache.get(seg.seg_id)
        if not own:
            return 0.0
        best = 0.0
        for other_id in context_ids:
            if other_id == seg.seg_id:
                continue
            other = shingle_cache.get(other_id)
            if not other:
                continue
            sim = _jaccard(own, other)
            if sim > best:
                best = sim
                if best >= 0.999:
                    break
        return best

    def _source_score(self, seg: Segment) -> float:
        """Score based on segment source prefix."""
        if seg.source is None:
            return 0.5
        prefix = seg.source.split(":")[0] if ":" in seg.source else seg.source
        return self.source_scores.get(prefix, 0.5)
