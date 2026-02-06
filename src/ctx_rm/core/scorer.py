"""Scorer: evaluates the value of each segment for eviction decisions.

The Scorer is pluggable — start with fast heuristics, optionally add
LLM-based scoring later. All scorers produce a composite_score in [0, 1]
where 0 = low value (evict first) and 1 = high value (keep).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

from ctx_rm.core.segment import Segment


class Scorer(ABC):
    """Base protocol for context scorers."""

    @abstractmethod
    def score_batch(
        self, candidates: list[Segment], context: list[Segment]
    ) -> None:
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
        role_scores: dict[str, float] | None = None,
        source_scores: dict[str, float] | None = None,
    ) -> None:
        self.recency_halflife = recency_halflife
        self.w_freq = frequency_weight
        self.w_rec = recency_weight
        self.w_role = role_weight
        self.w_source = source_weight

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

    def score_batch(
        self, candidates: list[Segment], context: list[Segment]
    ) -> None:
        for seg in candidates:
            seg.staleness_score = self._recency_score(seg)
            seg.relevance_score = self._frequency_score(seg)
            seg.redundancy_score = 0.0  # TODO: implement content dedup
            role_score = self.role_scores.get(seg.role.value, 0.5)

            base = (
                self.w_rec * seg.staleness_score
                + self.w_freq * seg.relevance_score
                + self.w_role * role_score
            )

            if self.w_source > 0:
                source_score = self._source_score(seg)
                seg.composite_score = base * (1 - self.w_source) + source_score * self.w_source
            else:
                seg.composite_score = base

    def _recency_score(self, seg: Segment) -> float:
        """Exponential decay: score = 2^(-idle / halflife)."""
        return math.pow(2, -seg.idle_seconds / self.recency_halflife)

    def _frequency_score(self, seg: Segment) -> float:
        """Log-scaled frequency: score = log2(1 + access_count) / 10, capped at 1."""
        return min(1.0, math.log2(1 + seg.access_count) / 10)

    def _source_score(self, seg: Segment) -> float:
        """Score based on segment source prefix."""
        if seg.source is None:
            return 0.5
        prefix = seg.source.split(":")[0] if ":" in seg.source else seg.source
        return self.source_scores.get(prefix, 0.5)
