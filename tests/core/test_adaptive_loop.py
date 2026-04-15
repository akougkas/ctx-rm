"""Tests for the closed adaptive→policy feedback loop."""

from __future__ import annotations

from ctx_rm.core.adaptive import (
    _AGGRESSIVENESS_STEP,
    _HIGH_RECALL_RATE,
    _MIN_EVENTS_FOR_SHIFT,
    AdaptiveWeights,
)
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.feedback import FeedbackTracker
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.segment import Segment, SegmentRole


def _seg(i: int, tokens: int = 50) -> Segment:
    return Segment(
        content=f"payload {i}",
        role=SegmentRole.USER,
        token_count=tokens,
        source="user_task",
    )


class TestPolicyAggressiveness:
    def test_default_aggressiveness_is_one(self) -> None:
        policy = LRUPolicy()
        assert policy.aggressiveness == 1.0

    def test_set_aggressiveness_clamps(self) -> None:
        policy = LRUPolicy()
        policy.set_aggressiveness(5.0)
        assert policy.aggressiveness == policy._AGGRESSIVENESS_MAX
        policy.set_aggressiveness(0.0)
        assert policy.aggressiveness == policy._AGGRESSIVENESS_MIN

    def test_aggressive_shift_frees_more(self) -> None:
        """mult > 1 causes the policy to free strictly more tokens when slack exists."""
        policy = LRUPolicy()
        candidates = [_seg(i, tokens=100) for i in range(10)]

        evicted_default = policy.select_evictions(list(candidates), tokens_to_free=100)
        assert sum(s.token_count for s in evicted_default) == 100

        policy2 = LRUPolicy()
        policy2.set_aggressiveness(2.0)
        # Fresh candidates so eviction state does not bleed across calls.
        candidates2 = [_seg(i, tokens=100) for i in range(10)]
        evicted_boosted = policy2.select_evictions(candidates2, tokens_to_free=100)
        assert sum(s.token_count for s in evicted_boosted) >= 200


class TestBusDrivesPolicyFromFeedback:
    def _bus(self) -> tuple[ContextBus, LRUPolicy, FeedbackTracker, AdaptiveWeights]:
        feedback = FeedbackTracker()
        adaptive = AdaptiveWeights()
        policy = LRUPolicy()
        bus = ContextBus(
            token_budget=1_000,
            store=TieredStore(),
            policy=policy,
            feedback=feedback,
            adaptive=adaptive,
            headroom_ratio=0.15,
        )
        return bus, policy, feedback, adaptive

    def test_conservative_shift_propagates_to_policy(self) -> None:
        bus, policy, feedback, adaptive = self._bus()

        # Seed enough events to trigger a conservative shift.
        seg = _seg(0)
        for i in range(_MIN_EVENTS_FOR_SHIFT + 2):
            s = _seg(i)
            feedback.on_eviction(s)
        # Recall rate >= _HIGH_RECALL_RATE
        for i in range(_MIN_EVENTS_FOR_SHIFT):
            feedback.on_recall(_seg(100 + i))

        bus._refresh_adaptive_policy_params()

        # Headroom should have grown, aggressiveness should have dropped.
        assert bus.headroom_ratio > 0.15
        assert policy.aggressiveness < 1.0 + 1e-9

    def test_aggressive_shift_raises_policy_aggressiveness(self) -> None:
        bus, policy, feedback, adaptive = self._bus()

        for i in range(_MIN_EVENTS_FOR_SHIFT + 2):
            feedback.on_eviction(_seg(i))
        # No recalls → recall rate == 0 → aggressive shift
        bus._refresh_adaptive_policy_params()
        assert policy.aggressiveness > 1.0
