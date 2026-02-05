"""Tests for the Segment data model."""

import time

from ctx_rm.core.segment import Segment, SegmentRole, Tier


def test_segment_creation():
    seg = Segment(content="hello world", role=SegmentRole.USER, token_count=3)
    assert seg.tier == Tier.ACTIVE
    assert seg.pinned is False
    assert seg.access_count == 0
    assert seg.ref_bit is True
    assert len(seg.seg_id) == 12


def test_segment_touch():
    seg = Segment(content="test", role=SegmentRole.USER, token_count=1)
    old_access = seg.last_accessed
    time.sleep(0.01)
    seg.touch()
    assert seg.access_count == 1
    assert seg.last_accessed > old_access
    assert seg.ref_bit is True


def test_segment_evict():
    seg = Segment(content="test", role=SegmentRole.TOOL, token_count=100)
    seg.evict(reason="lru:idle_30s", policy="lru")
    assert seg.evicted_at is not None
    assert seg.eviction_reason == "lru:idle_30s"
    assert seg.eviction_policy == "lru"


def test_segment_recall():
    seg = Segment(content="recalled", role=SegmentRole.ASSISTANT, token_count=50)
    seg.tier = Tier.COLD
    seg.recall()
    assert seg.tier == Tier.ZOMBIE
    assert seg.recalled_at is not None
    assert seg.access_count == 1


def test_segment_repr():
    seg = Segment(content="test", role=SegmentRole.USER, token_count=42)
    r = repr(seg)
    assert "user" in r
    assert "act" in r
    assert "42tok" in r
