"""Circuit breaker tests for SequentialScorer."""

from __future__ import annotations

from typing import Any

from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.scorer_sequential import SequentialScorer
from ctx_rm.core.segment import Segment, SegmentRole


def _seg(i: int) -> Segment:
    return Segment(
        content=f"content payload number {i}",
        role=SegmentRole.USER,
        token_count=10,
        source="user_task",
    )


class _FailingScorer:
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def __call__(self, content: str, retained: str, task: str) -> dict[str, float]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"llm error {self.calls}")
        return {
            "relevance_score": 0.5,
            "staleness_score": 0.5,
            "redundancy_score": 0.0,
            "composite_score": 0.5,
        }


class TestCircuitBreaker:
    def test_breaker_trips_after_threshold(self) -> None:
        fn = _FailingScorer(fail_times=100)
        scorer = SequentialScorer(
            scoring_fn=fn,
            task_goal="task",
            fallback=HeuristicScorer(),
            failure_threshold=3,
        )
        candidates = [_seg(i) for i in range(10)]
        scorer.score_batch(candidates, candidates)
        stats = scorer.get_stats()
        assert stats["breaker_open"] is True
        assert stats["total_failures"] >= 3
        # Once tripped we stop hammering the backend.
        assert fn.calls <= 5
        # All segments have composite scores from the fallback.
        for seg in candidates:
            assert seg.composite_score is not None

    def test_breaker_resets_on_success(self) -> None:
        fn = _FailingScorer(fail_times=2)
        scorer = SequentialScorer(
            scoring_fn=fn,
            task_goal="task",
            fallback=HeuristicScorer(),
            failure_threshold=5,
        )
        candidates = [_seg(i) for i in range(5)]
        scorer.score_batch(candidates, candidates)
        stats = scorer.get_stats()
        assert stats["breaker_open"] is False
        assert stats["consecutive_failures"] == 0
        assert stats["total_successes"] >= 1

    def test_breaker_open_skips_callable(self) -> None:
        fn = _FailingScorer(fail_times=100)
        scorer = SequentialScorer(
            scoring_fn=fn,
            task_goal="task",
            fallback=HeuristicScorer(),
            failure_threshold=2,
        )
        # First batch trips the breaker.
        scorer.score_batch([_seg(i) for i in range(3)], [])
        prior_calls = fn.calls
        # Second batch: should not call fn at all.
        scorer.score_batch([_seg(i) for i in range(3)], [])
        assert fn.calls == prior_calls
