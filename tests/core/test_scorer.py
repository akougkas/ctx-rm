"""Tests for HeuristicScorer — especially source-aware scoring.

Verifies that when source_weight > 0, needle segments score higher
than noise segments, and under eviction pressure noise is evicted first.
"""

from __future__ import annotations

import pytest

from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.segment import Segment, SegmentRole


def _make_segment(source: str, role: SegmentRole = SegmentRole.CONTEXT, tokens: int = 20) -> Segment:
    return Segment(
        content=f"content for {source}",
        role=role,
        token_count=tokens,
        source=source,
    )


class TestHeuristicScorerDefaults:
    """Default scorer (source_weight=0) — blind to source."""

    def test_same_role_same_time_same_score(self) -> None:
        """Two CONTEXT segments created at same time should score ~equal."""
        scorer = HeuristicScorer()
        needle = _make_segment("needle:N1")
        noise = _make_segment("noise:logs")

        scorer.score_batch([needle, noise], [needle, noise])

        assert abs(needle.composite_score - noise.composite_score) < 0.01

    def test_system_scores_higher_than_context(self) -> None:
        """System role should score higher than context role."""
        scorer = HeuristicScorer()
        system = _make_segment("system_prompt", role=SegmentRole.SYSTEM)
        ctx = _make_segment("noise:logs", role=SegmentRole.CONTEXT)

        scorer.score_batch([system, ctx], [system, ctx])

        assert system.composite_score > ctx.composite_score


class TestHeuristicScorerSourceAware:
    """Source-aware scorer (source_weight > 0)."""

    def test_needle_scores_higher_than_noise(self) -> None:
        """With source_weight > 0, needle must score higher than noise."""
        scorer = HeuristicScorer(source_weight=0.3)
        needle = _make_segment("needle:N1")
        noise = _make_segment("noise:logs")

        scorer.score_batch([needle, noise], [needle, noise])

        assert needle.composite_score > noise.composite_score

    def test_needle_scores_higher_than_generic_context(self) -> None:
        """Needle should score higher than unlabeled context too."""
        scorer = HeuristicScorer(source_weight=0.3)
        needle = _make_segment("needle:N1")
        generic = _make_segment("unknown_source")

        scorer.score_batch([needle, generic], [needle, generic])

        assert needle.composite_score > generic.composite_score

    def test_custom_source_scores(self) -> None:
        """Custom source_scores dict is respected."""
        scorer = HeuristicScorer(
            source_weight=0.5,
            source_scores={"important": 1.0, "junk": 0.0},
        )
        important = _make_segment("important:doc")
        junk = _make_segment("junk:garbage")

        scorer.score_batch([important, junk], [important, junk])

        assert important.composite_score > junk.composite_score

    def test_source_weight_zero_ignores_source(self) -> None:
        """source_weight=0 makes scorer blind to source (backward compat)."""
        scorer = HeuristicScorer(source_weight=0.0)
        needle = _make_segment("needle:N1")
        noise = _make_segment("noise:logs")

        scorer.score_batch([needle, noise], [needle, noise])

        assert abs(needle.composite_score - noise.composite_score) < 0.01


class TestScorerWithEviction:
    """Integration: scorer + bus + policy → noise evicted before needles."""

    def test_budget_policy_evicts_noise_before_needle(self) -> None:
        """BudgetAwarePolicy uses composite_score → noise dies first."""
        from ctx_rm.core.bus import ContextBus
        from ctx_rm.core.graveyard import TieredStore
        from ctx_rm.core.policies import BudgetAwarePolicy

        scorer = HeuristicScorer(source_weight=0.3)
        bus = ContextBus(
            token_budget=100,
            store=TieredStore(),
            policy=BudgetAwarePolicy(),
            scorer=scorer,
        )

        needle = Segment(
            content="The answer is 42",
            role=SegmentRole.CONTEXT,
            token_count=20,
            source="needle:N1",
        )
        noise = Segment(
            content="irrelevant " * 20,
            role=SegmentRole.CONTEXT,
            token_count=80,
            source="noise:junk",
        )

        bus.ingest(needle)  # active=20, under headroom(85)
        bus.ingest(noise)  # active=100, over headroom(85) → eviction

        # Needle must survive, noise must be evicted
        active_sources = {s.source for s in bus.active_segments}
        assert "needle:N1" in active_sources, "Needle should survive eviction"
        assert "noise:junk" not in active_sources, "Noise should be evicted"

    def test_lru_still_evicts_needle_first(self) -> None:
        """LRU ignores scores — needle injected first gets evicted first.
        This proves LRU is not the right policy for needle retention."""
        from ctx_rm.core.bus import ContextBus
        from ctx_rm.core.graveyard import TieredStore
        from ctx_rm.core.policies import LRUPolicy

        scorer = HeuristicScorer(source_weight=0.3)
        bus = ContextBus(
            token_budget=100,
            store=TieredStore(),
            policy=LRUPolicy(),
            scorer=scorer,
        )

        needle = Segment(
            content="The answer is 42",
            role=SegmentRole.CONTEXT,
            token_count=20,
            source="needle:N1",
        )
        noise = Segment(
            content="irrelevant " * 20,
            role=SegmentRole.CONTEXT,
            token_count=80,
            source="noise:junk",
        )

        bus.ingest(needle)  # injected first → oldest
        bus.ingest(noise)  # injected second → eviction triggers

        # LRU evicts oldest first regardless of score → needle dies
        active_sources = {s.source for s in bus.active_segments}
        assert "needle:N1" not in active_sources, "LRU evicts oldest (needle) first"

    def test_multiple_noise_segments_evicted_before_needle(self) -> None:
        """Multiple noise segments should all be evicted before needle."""
        from ctx_rm.core.bus import ContextBus
        from ctx_rm.core.graveyard import TieredStore
        from ctx_rm.core.policies import BudgetAwarePolicy

        scorer = HeuristicScorer(source_weight=0.3)
        bus = ContextBus(
            token_budget=200,
            store=TieredStore(),
            policy=BudgetAwarePolicy(),
            scorer=scorer,
        )

        needle = Segment(
            content="critical fact", role=SegmentRole.CONTEXT,
            token_count=20, source="needle:N1",
        )
        noise1 = Segment(
            content="noise1 " * 20, role=SegmentRole.CONTEXT,
            token_count=80, source="noise:log1",
        )
        noise2 = Segment(
            content="noise2 " * 20, role=SegmentRole.CONTEXT,
            token_count=80, source="noise:log2",
        )

        bus.ingest(needle)   # 20
        bus.ingest(noise1)   # 100
        bus.ingest(noise2)   # 180, over headroom(170) → eviction

        active_sources = {s.source for s in bus.active_segments}
        assert "needle:N1" in active_sources
