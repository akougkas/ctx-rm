"""Tests for SequentialScorer — task-aware conditional scoring with cache."""

from __future__ import annotations

import pytest

from ctx_rm.core.scorer_sequential import (
    SequentialScorer,
    summarize_retained_set,
    _hash,
)
from ctx_rm.core.segment import Segment, SegmentRole


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seg(content: str = "test content", source: str = "test", tokens: int = 10) -> Segment:
    return Segment(
        content=content,
        role=SegmentRole.CONTEXT,
        token_count=tokens,
        source=source,
    )


def _good_scoring_fn(content: str, retained: str, task: str) -> dict[str, float]:
    """Deterministic scoring fn: scores based on content length ratio."""
    base = min(1.0, len(content) / 100)
    return {
        "relevance_score": base,
        "staleness_score": 0.5,
        "redundancy_score": 0.1,
        "composite_score": base * 0.8 + 0.1,
    }


def _failing_scoring_fn(content: str, retained: str, task: str) -> dict[str, float]:
    raise RuntimeError("LLM unavailable")


def _invalid_scoring_fn(content: str, retained: str, task: str) -> dict[str, float]:
    """Returns dict missing required keys."""
    return {"relevance_score": 0.5}


def _bad_type_scoring_fn(content: str, retained: str, task: str) -> dict[str, float]:
    """Returns dict with non-numeric values."""
    return {
        "relevance_score": "high",  # type: ignore[dict-item]
        "staleness_score": 0.5,
        "redundancy_score": 0.1,
        "composite_score": 0.7,
    }


# ── summarize_retained_set ────────────────────────────────────────────────


class TestSummarizeRetainedSet:
    def test_empty_list(self) -> None:
        assert summarize_retained_set([]) == ""

    def test_single_segment(self) -> None:
        seg = _seg("hello world")
        result = summarize_retained_set([seg])
        assert "[context]" in result
        assert "hello world" in result

    def test_truncates_long_content(self) -> None:
        seg = _seg("x" * 500)
        result = summarize_retained_set([seg])
        assert "..." in result
        assert len(result) < 500

    def test_respects_total_limit(self) -> None:
        segs = [_seg(f"content {i}" * 20) for i in range(50)]
        result = summarize_retained_set(segs, max_total=200)
        assert len(result) <= 220  # allow small overshoot from last truncated line

    def test_deterministic_output(self) -> None:
        segs = [_seg(f"seg-{i}") for i in range(5)]
        r1 = summarize_retained_set(segs)
        r2 = summarize_retained_set(segs)
        assert r1 == r2


# ── SequentialScorer basic scoring ───────────────────────────────────────


class TestSequentialScorerBasic:
    def test_scores_candidates_in_place(self) -> None:
        scorer = SequentialScorer(scoring_fn=_good_scoring_fn, task_goal="fix bug")
        candidates = [_seg("short"), _seg("a much longer content string " * 5)]
        context = [_seg("retained context")]

        scorer.score_batch(candidates, context)

        for seg in candidates:
            assert seg.relevance_score is not None
            assert seg.staleness_score is not None
            assert seg.redundancy_score is not None
            assert seg.composite_score is not None
            assert 0.0 <= seg.composite_score <= 1.0

    def test_longer_content_scores_higher(self) -> None:
        """_good_scoring_fn uses content length → longer = higher relevance."""
        scorer = SequentialScorer(scoring_fn=_good_scoring_fn, task_goal="test")
        short = _seg("hi")
        long = _seg("a" * 90)

        scorer.score_batch([short, long], [])

        assert long.relevance_score > short.relevance_score

    def test_sets_all_four_score_fields(self) -> None:
        scorer = SequentialScorer(scoring_fn=_good_scoring_fn)
        seg = _seg()
        scorer.score_batch([seg], [])

        assert seg.relevance_score is not None
        assert seg.staleness_score is not None
        assert seg.redundancy_score is not None
        assert seg.composite_score is not None


# ── Fallback behavior ────────────────────────────────────────────────────


class TestSequentialScorerFallback:
    def test_fallback_on_exception(self) -> None:
        """When scoring_fn raises, fallback scorer fills in scores."""
        scorer = SequentialScorer(scoring_fn=_failing_scoring_fn, task_goal="test")
        seg = _seg()

        scorer.score_batch([seg], [])

        # HeuristicScorer fallback should have set composite_score
        assert seg.composite_score is not None

    def test_fallback_on_invalid_result(self) -> None:
        """When scoring_fn returns incomplete dict, fallback handles it."""
        scorer = SequentialScorer(scoring_fn=_invalid_scoring_fn, task_goal="test")
        seg = _seg()

        scorer.score_batch([seg], [])

        assert seg.composite_score is not None

    def test_fallback_on_bad_types(self) -> None:
        """When scoring_fn returns non-numeric values, fallback handles it."""
        scorer = SequentialScorer(scoring_fn=_bad_type_scoring_fn, task_goal="test")
        seg = _seg()

        scorer.score_batch([seg], [])

        assert seg.composite_score is not None

    def test_no_scoring_fn_delegates_to_fallback(self) -> None:
        """When scoring_fn is None, entire batch goes to fallback."""
        scorer = SequentialScorer(scoring_fn=None, task_goal="test")
        seg = _seg()

        scorer.score_batch([seg], [])

        assert seg.composite_score is not None

    def test_partial_failure_mixes_scorers(self) -> None:
        """Some segments scored by fn, failed ones by fallback."""
        call_count = 0

        def flaky_fn(content: str, retained: str, task: str) -> dict[str, float]:
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("intermittent failure")
            return {
                "relevance_score": 0.9,
                "staleness_score": 0.5,
                "redundancy_score": 0.1,
                "composite_score": 0.85,
            }

        scorer = SequentialScorer(scoring_fn=flaky_fn, task_goal="test")
        segs = [_seg(f"seg-{i}") for i in range(4)]

        scorer.score_batch(segs, [])

        # All segments should have scores (mix of fn + fallback)
        for seg in segs:
            assert seg.composite_score is not None


# ── Cache behavior ───────────────────────────────────────────────────────


class TestSequentialScorerCache:
    def test_cache_hit_avoids_second_call(self) -> None:
        call_count = 0

        def counting_fn(content: str, retained: str, task: str) -> dict[str, float]:
            nonlocal call_count
            call_count += 1
            return {
                "relevance_score": 0.7,
                "staleness_score": 0.5,
                "redundancy_score": 0.1,
                "composite_score": 0.6,
            }

        scorer = SequentialScorer(scoring_fn=counting_fn, task_goal="test")
        seg1 = _seg("same content")
        seg2 = _seg("same content")

        scorer.score_batch([seg1], [])
        scorer.score_batch([seg2], [])

        assert call_count == 1
        assert seg2.composite_score == seg1.composite_score

    def test_different_content_no_cache_hit(self) -> None:
        call_count = 0

        def counting_fn(content: str, retained: str, task: str) -> dict[str, float]:
            nonlocal call_count
            call_count += 1
            return {
                "relevance_score": 0.7,
                "staleness_score": 0.5,
                "redundancy_score": 0.1,
                "composite_score": 0.6,
            }

        scorer = SequentialScorer(scoring_fn=counting_fn, task_goal="test")
        scorer.score_batch([_seg("content A")], [])
        scorer.score_batch([_seg("content B")], [])

        assert call_count == 2

    def test_different_context_invalidates_cache(self) -> None:
        """Same segment content but different retained context = cache miss."""
        call_count = 0

        def counting_fn(content: str, retained: str, task: str) -> dict[str, float]:
            nonlocal call_count
            call_count += 1
            return {
                "relevance_score": 0.7,
                "staleness_score": 0.5,
                "redundancy_score": 0.1,
                "composite_score": 0.6,
            }

        scorer = SequentialScorer(scoring_fn=counting_fn, task_goal="test")
        seg1 = _seg("target")
        seg2 = _seg("target")

        scorer.score_batch([seg1], [_seg("context A")])
        scorer.score_batch([seg2], [_seg("context B")])

        assert call_count == 2

    def test_different_task_invalidates_cache(self) -> None:
        """Same content+context but different task_goal = different scorer instance."""
        call_count = 0

        def counting_fn(content: str, retained: str, task: str) -> dict[str, float]:
            nonlocal call_count
            call_count += 1
            return {
                "relevance_score": 0.7,
                "staleness_score": 0.5,
                "redundancy_score": 0.1,
                "composite_score": 0.6,
            }

        scorer_a = SequentialScorer(scoring_fn=counting_fn, task_goal="task A")
        scorer_b = SequentialScorer(scoring_fn=counting_fn, task_goal="task B")

        scorer_a.score_batch([_seg("target")], [])
        scorer_b.score_batch([_seg("target")], [])

        assert call_count == 2


# ── Score clamping ───────────────────────────────────────────────────────


class TestSequentialScorerClamping:
    def test_scores_clamped_to_0_1(self) -> None:
        def out_of_range_fn(content: str, retained: str, task: str) -> dict[str, float]:
            return {
                "relevance_score": 1.5,
                "staleness_score": -0.3,
                "redundancy_score": 2.0,
                "composite_score": -1.0,
            }

        scorer = SequentialScorer(scoring_fn=out_of_range_fn, task_goal="test")
        seg = _seg()
        scorer.score_batch([seg], [])

        assert seg.relevance_score == 1.0
        assert seg.staleness_score == 0.0
        assert seg.redundancy_score == 1.0
        assert seg.composite_score == 0.0


# ── Integration with Scorer ABC ──────────────────────────────────────────


class TestSequentialScorerIsScorer:
    def test_isinstance_of_scorer(self) -> None:
        from ctx_rm.core.scorer import Scorer

        scorer = SequentialScorer(scoring_fn=_good_scoring_fn)
        assert isinstance(scorer, Scorer)
