"""Tests for eviction policies."""

import time

from ctx_rm.core.policies.budget import BudgetAwarePolicy
from ctx_rm.core.policies.clock import ClockPolicy
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.segment import Segment, SegmentRole


def _make_seg(content: str = "test", tokens: int = 100, idle: float = 0) -> Segment:
    seg = Segment(content=content, role=SegmentRole.USER, token_count=tokens)
    if idle > 0:
        seg.last_accessed = time.time() - idle
    return seg


# ── LRU ─────────────────────────────────────────────────────────────────


def test_lru_evicts_oldest():
    policy = LRUPolicy()
    old = _make_seg("old", tokens=100, idle=60)
    new = _make_seg("new", tokens=100, idle=1)

    evicted = policy.select_evictions([old, new], tokens_to_free=100)
    assert len(evicted) == 1
    assert evicted[0].seg_id == old.seg_id


def test_lru_evicts_multiple():
    policy = LRUPolicy()
    segs = [_make_seg(f"seg_{i}", tokens=50, idle=100 - i) for i in range(5)]

    evicted = policy.select_evictions(segs, tokens_to_free=120)
    assert sum(s.token_count for s in evicted) >= 120


# ── CLOCK ───────────────────────────────────────────────────────────────


def test_clock_respects_ref_bit():
    policy = ClockPolicy()
    s1 = _make_seg("referenced", tokens=100)
    s1.ref_bit = True
    s2 = _make_seg("unreferenced", tokens=100)
    s2.ref_bit = False

    evicted = policy.select_evictions([s1, s2], tokens_to_free=100)
    assert len(evicted) == 1
    assert evicted[0].seg_id == s2.seg_id


def test_clock_clears_ref_bit():
    policy = ClockPolicy()
    s1 = _make_seg("ref", tokens=100)
    s1.ref_bit = True

    # With only one segment that has ref_bit=True, clock should clear it
    # then evict on second pass
    evicted = policy.select_evictions([s1], tokens_to_free=100)
    assert len(evicted) == 1


# ── BudgetAware ─────────────────────────────────────────────────────────


def test_budget_aware_evicts_lowest_score():
    policy = BudgetAwarePolicy()
    low = _make_seg("low", tokens=100)
    low.composite_score = 0.1
    high = _make_seg("high", tokens=100)
    high.composite_score = 0.9

    evicted = policy.select_evictions([low, high], tokens_to_free=100)
    assert len(evicted) == 1
    assert evicted[0].seg_id == low.seg_id


def test_budget_aware_falls_back_to_lru():
    policy = BudgetAwarePolicy()
    old = _make_seg("old", tokens=100, idle=60)  # No score
    new = _make_seg("new", tokens=100, idle=1)  # No score

    evicted = policy.select_evictions([old, new], tokens_to_free=100)
    assert len(evicted) == 1
    assert evicted[0].seg_id == old.seg_id
