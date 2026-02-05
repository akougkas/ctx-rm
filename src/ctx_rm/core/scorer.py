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

    Combines three signals:
      - Recency: exponential decay based on idle time
      - Frequency: log-scaled access count
      - Role weight: system > user > assistant > tool (configurable)

    This is the default scorer for benchmarks where we want zero overhead.
    """

    def __init__(
        self,
        recency_halflife: float = 300.0,  # 5 minutes
        frequency_weight: float = 0.2,
        recency_weight: float = 0.5,
        role_weight: float = 0.3,
        role_scores: dict[str, float] | None = None,
    ) -> None:
        self.recency_halflife = recency_halflife
        self.w_freq = frequency_weight
        self.w_rec = recency_weight
        self.w_role = role_weight

        self.role_scores = role_scores or {
            "system": 1.0,
            "user": 0.8,
            "assistant": 0.5,
            "tool": 0.3,
        }

    def score_batch(
        self, candidates: list[Segment], context: list[Segment]
    ) -> None:
        for seg in candidates:
            seg.staleness_score = self._recency_score(seg)
            seg.relevance_score = self._frequency_score(seg)
            seg.redundancy_score = 0.0  # TODO: implement content dedup
            role_score = self.role_scores.get(seg.role.value, 0.5)

            seg.composite_score = (
                self.w_rec * seg.staleness_score
                + self.w_freq * seg.relevance_score
                + self.w_role * role_score
            )

    def _recency_score(self, seg: Segment) -> float:
        """Exponential decay: score = 2^(-idle / halflife)."""
        return math.pow(2, -seg.idle_seconds / self.recency_halflife)

    def _frequency_score(self, seg: Segment) -> float:
        """Log-scaled frequency: score = log2(1 + access_count) / 10, capped at 1."""
        return min(1.0, math.log2(1 + seg.access_count) / 10)
