"""Tests for eviction policies."""

import time

from ctx_rm.core.policies.arc import ARCPolicy
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


# ── ARC ────────────────────────────────────────────────────────────────


def test_arc_ingest_adds_to_t1():
    """New segments go to T1 (recency list)."""
    policy = ARCPolicy(capacity_tokens=10000)
    seg = _make_seg("hello", tokens=100)

    policy.on_ingest(seg)

    assert seg.seg_id in policy._t1
    assert seg.seg_id not in policy._t2


def test_arc_access_promotes_t1_to_t2():
    """Accessing a T1 segment promotes it to T2 (frequency list)."""
    policy = ARCPolicy(capacity_tokens=10000)
    seg = _make_seg("hello", tokens=100)

    policy.on_ingest(seg)
    assert seg.seg_id in policy._t1

    policy.on_access(seg)
    assert seg.seg_id not in policy._t1
    assert seg.seg_id in policy._t2


def test_arc_evict_from_t1_creates_b1_ghost():
    """Evicting a T1 segment adds a ghost entry to B1."""
    policy = ARCPolicy(capacity_tokens=10000)
    seg = _make_seg("ghost-me", tokens=200)

    policy.on_ingest(seg)
    policy.on_evict(seg)

    assert seg.seg_id not in policy._t1
    assert seg.seg_id in policy._b1
    assert policy._b1[seg.seg_id] == 200


def test_arc_evict_from_t2_creates_b2_ghost():
    """Evicting a T2 segment adds a ghost entry to B2."""
    policy = ARCPolicy(capacity_tokens=10000)
    seg = _make_seg("freq", tokens=150)

    policy.on_ingest(seg)
    policy.on_access(seg)  # promote to T2
    policy.on_evict(seg)

    assert seg.seg_id not in policy._t2
    assert seg.seg_id in policy._b2
    assert policy._b2[seg.seg_id] == 150


def test_arc_ghost_hit_b1_increases_p():
    """Re-ingesting a B1 ghost segment increases p (favor recency)."""
    policy = ARCPolicy(capacity_tokens=10000)
    seg = _make_seg("recency", tokens=100)

    # Ingest -> evict (creates B1 ghost) -> re-ingest (ghost hit)
    policy.on_ingest(seg)
    policy.on_evict(seg)
    assert seg.seg_id in policy._b1

    p_before = policy._p
    policy.on_ingest(seg)

    assert policy._p > p_before
    assert seg.seg_id not in policy._b1
    assert seg.seg_id in policy._t2  # promoted to frequency on ghost hit


def test_arc_ghost_hit_b2_decreases_p():
    """Re-ingesting a B2 ghost segment decreases p (favor frequency)."""
    policy = ARCPolicy(capacity_tokens=10000)
    seg = _make_seg("frequency", tokens=100)

    # Ingest -> access (T1->T2) -> evict (creates B2 ghost)
    policy.on_ingest(seg)
    policy.on_access(seg)
    policy.on_evict(seg)
    assert seg.seg_id in policy._b2

    # Set p high so we can see it decrease
    policy._p = 5000.0
    p_before = policy._p
    policy.on_ingest(seg)

    assert policy._p < p_before
    assert seg.seg_id not in policy._b2
    assert seg.seg_id in policy._t2


def test_arc_select_evictions_respects_p():
    """When T1 tokens exceed p, select_evictions prefers T1 tail for eviction."""
    policy = ARCPolicy(capacity_tokens=10000)
    policy._p = 0.0  # Force T1 eviction priority (T1 > p=0)

    t1_seg = _make_seg("t1_old", tokens=100)
    t2_seg = _make_seg("t2_old", tokens=100)

    policy.on_ingest(t1_seg)   # goes to T1
    policy.on_ingest(t2_seg)   # goes to T1
    policy.on_access(t2_seg)   # promote to T2

    evicted = policy.select_evictions([t1_seg, t2_seg], tokens_to_free=100)
    assert len(evicted) == 1
    assert evicted[0].seg_id == t1_seg.seg_id  # T1 evicted first


def test_arc_ghost_list_bounded():
    """Ghost lists are trimmed when they exceed capacity_tokens."""
    policy = ARCPolicy(capacity_tokens=500)

    # Create and evict enough segments to overflow B1
    segments = []
    for i in range(10):
        seg = _make_seg(f"seg_{i}", tokens=100)
        segments.append(seg)
        policy.on_ingest(seg)
        policy.on_evict(seg)

    # B1 total tokens should not exceed capacity (500)
    b1_total = sum(policy._b1.values())
    assert b1_total <= 500
