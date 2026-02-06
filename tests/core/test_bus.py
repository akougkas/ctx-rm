"""Tests for the ContextBus."""

from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.segment import Segment, SegmentRole, Tier


def _make_seg(content: str = "test", tokens: int = 100, role: str = "user") -> Segment:
    return Segment(content=content, role=SegmentRole(role), token_count=tokens)


def test_ingest_adds_to_active():
    store = TieredStore()
    bus = ContextBus(token_budget=1000, store=store, policy=LRUPolicy())

    seg = _make_seg(tokens=100)
    bus.ingest(seg)

    assert bus.active_tokens == 100
    assert len(bus.active_segments) == 1
    assert bus.active_segments[0].tier == Tier.ACTIVE


def test_eviction_triggers_on_budget():
    store = TieredStore()
    bus = ContextBus(
        token_budget=500, store=store, policy=LRUPolicy(), headroom_ratio=0.2
    )
    # Headroom target = 500 * 0.8 = 400

    # Ingest 5 segments of 100 tokens each = 500 total
    segments = []
    for i in range(5):
        seg = _make_seg(content=f"seg_{i}", tokens=100)
        bus.ingest(seg)
        segments.append(seg)

    # Should have evicted some to get under 400
    assert bus.active_tokens <= 400
    assert store.warm.count > 0


def test_pinned_segments_not_evicted():
    store = TieredStore()
    bus = ContextBus(
        token_budget=300, store=store, policy=LRUPolicy(), headroom_ratio=0.2
    )

    pinned = _make_seg(content="system prompt", tokens=100, role="system")
    pinned.pinned = True
    bus.ingest(pinned)

    # Fill past budget
    for i in range(3):
        bus.ingest(_make_seg(content=f"filler_{i}", tokens=100))

    # Pinned segment should still be in active
    active_ids = {s.seg_id for s in bus.active_segments}
    assert pinned.seg_id in active_ids


def test_recall_from_warm():
    store = TieredStore()
    bus = ContextBus(
        token_budget=200, store=store, policy=LRUPolicy(), headroom_ratio=0.2
    )

    seg = _make_seg(content="important", tokens=100)
    bus.ingest(seg)
    evicted_id = seg.seg_id

    # Force eviction by adding more
    bus.ingest(_make_seg(tokens=100))
    bus.ingest(_make_seg(tokens=100))

    # Now recall the evicted segment
    recalled = bus.recall(evicted_id)
    assert recalled is not None
    assert recalled.content == "important"


def test_render_context():
    store = TieredStore()
    bus = ContextBus(token_budget=1000, store=store, policy=LRUPolicy())

    bus.ingest(_make_seg(content="hello", tokens=10, role="user"))
    bus.ingest(_make_seg(content="world", tokens=10, role="assistant"))

    rendered = bus.render_context()
    assert len(rendered) == 2
    assert rendered[0]["role"] == "user"
    assert rendered[0]["content"] == "hello"
    assert rendered[1]["role"] == "assistant"


def test_stats():
    store = TieredStore()
    bus = ContextBus(token_budget=1000, store=store, policy=LRUPolicy())
    bus.ingest(_make_seg(tokens=100))

    stats = bus.get_stats()
    assert stats["active_segments"] == 1
    assert stats["active_tokens"] == 100
    assert stats["budget"] == 1000


# ── Admission Control ────────────────────────────────────────────────────


def test_admission_large_file_read_bypasses_active():
    """Large file_read segments go directly to Warm, not Active."""
    store = TieredStore()
    bus = ContextBus(
        token_budget=10000, store=store, policy=LRUPolicy(), admission_threshold=500
    )

    seg = _make_seg(content="big file", tokens=1000)
    seg.source = "file_read:src/huge.py"
    bus.ingest(seg)

    assert seg.seg_id not in {s.seg_id for s in bus.active_segments}
    assert seg.tier == Tier.WARM
    assert bus.active_tokens == 0
    assert store.warm.count > 0


def test_admission_small_file_read_enters_active():
    """Small file_read segments below threshold enter Active normally."""
    store = TieredStore()
    bus = ContextBus(
        token_budget=10000, store=store, policy=LRUPolicy(), admission_threshold=500
    )

    seg = _make_seg(content="small file", tokens=200)
    seg.source = "file_read:src/tiny.py"
    bus.ingest(seg)

    assert seg.seg_id in {s.seg_id for s in bus.active_segments}
    assert seg.tier == Tier.ACTIVE
    assert bus.active_tokens == 200


def test_admission_user_message_not_affected():
    """User messages are never subject to admission control regardless of size."""
    store = TieredStore()
    bus = ContextBus(
        token_budget=10000, store=store, policy=LRUPolicy(), admission_threshold=500
    )

    seg = _make_seg(content="large user prompt", tokens=3000)
    seg.source = "user_message"
    bus.ingest(seg)

    assert seg.seg_id in {s.seg_id for s in bus.active_segments}
    assert seg.tier == Tier.ACTIVE
    assert bus.active_tokens == 3000
