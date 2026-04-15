"""Redundancy scoring tests for HeuristicScorer.

Verifies that duplicate content reduces composite score and that the
5-shingle Jaccard signal catches both byte-identical and paraphrase
duplicates.
"""

from __future__ import annotations

from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.segment import Segment, SegmentRole


def _seg(content: str, source: str = "tool:file_read") -> Segment:
    return Segment(
        content=content,
        role=SegmentRole.TOOL,
        token_count=len(content) // 4 or 1,
        source=source,
    )


class TestRedundancyScoring:
    def test_identical_content_gets_high_redundancy(self) -> None:
        scorer = HeuristicScorer(redundancy_weight=0.3)
        body = "the quick brown fox jumps over the lazy dog repeatedly today"
        a = _seg(body)
        b = _seg(body)
        scorer.score_batch([a, b], context=[a, b])
        assert a.redundancy_score == 1.0
        assert b.redundancy_score == 1.0

    def test_disjoint_content_has_zero_redundancy(self) -> None:
        scorer = HeuristicScorer()
        a = _seg("alpha bravo charlie delta echo foxtrot golf hotel india")
        b = _seg("xenon yankee zulu omega sigma tau upsilon phi chi")
        scorer.score_batch([a, b], context=[a, b])
        assert a.redundancy_score == 0.0
        assert b.redundancy_score == 0.0

    def test_redundancy_penalizes_composite_score(self) -> None:
        scorer = HeuristicScorer(redundancy_weight=0.5)
        body = "the quick brown fox jumps over the lazy dog repeatedly today"
        dup_a = _seg(body)
        dup_b = _seg(body)
        unique = _seg("completely unrelated content token stream zeta omega alpha")
        # Align access pattern so only redundancy differs.
        dup_a.last_accessed = unique.last_accessed
        dup_b.last_accessed = unique.last_accessed
        dup_a.created_at = unique.created_at
        dup_b.created_at = unique.created_at
        dup_a.access_count = unique.access_count
        dup_b.access_count = unique.access_count
        dup_a.role = unique.role
        dup_b.role = unique.role

        scorer.score_batch([dup_a, unique], context=[dup_a, dup_b, unique])

        assert dup_a.composite_score is not None
        assert unique.composite_score is not None
        assert dup_a.composite_score < unique.composite_score

    def test_excludes_self_from_redundancy(self) -> None:
        """A segment compared against itself alone yields zero redundancy."""
        scorer = HeuristicScorer()
        body = "the quick brown fox jumps over the lazy dog repeatedly today"
        seg = _seg(body)
        scorer.score_batch([seg], context=[seg])
        assert seg.redundancy_score == 0.0

    def test_partial_overlap_between_zero_and_one(self) -> None:
        """Shared 5+-token run yields non-zero but sub-unity redundancy."""
        scorer = HeuristicScorer()
        shared = "the quick brown fox jumps over the lazy dog"
        a = _seg(f"{shared} in summer heat and winter cold and every season")
        b = _seg(f"{shared} across rivers valleys and mountains for many days")
        scorer.score_batch([a, b], context=[a, b])
        assert 0.0 < a.redundancy_score < 1.0
