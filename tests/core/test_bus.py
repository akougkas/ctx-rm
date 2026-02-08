"""Tests for the ContextBus."""

from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.segment import Segment, SegmentRole, Tier


def _make_seg(content: str = "test", tokens: int = 100, role: str = "user") -> Segment:
    return Segment(content=content, role=SegmentRole(role), token_count=tokens)


class RecordingPolicy(EvictionPolicy):
    """Policy test double that records requested eviction token targets."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    @property
    def name(self) -> str:
        return "recording"

    def select_evictions(self, candidates: list[Segment], tokens_to_free: int) -> list[Segment]:
        self.calls.append(tokens_to_free)
        ranked = sorted(candidates, key=lambda s: s.created_at)
        return self._fill_to_budget(ranked, tokens_to_free)


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


# ── Evicted segment search ──────────────────────────────────────────────


def test_evicted_segment_searchable_in_warm():
    """Evicted segments in warm cache are found by search_evicted()."""
    from ctx_rm.core.embedding import HashingEmbeddingProvider

    store = TieredStore(embedding_provider=HashingEmbeddingProvider())
    bus = ContextBus(
        token_budget=200, store=store, policy=LRUPolicy(), headroom_ratio=0.2
    )

    # Ingest a needle with distinctive content
    needle = _make_seg(content="CRITICAL: port must be 9876", tokens=100)
    needle.source = "needle:N1"
    bus.ingest(needle)
    needle_id = needle.seg_id

    # Force eviction by filling past budget
    bus.ingest(_make_seg(content="filler A", tokens=100))
    bus.ingest(_make_seg(content="filler B", tokens=100))

    # Needle should be evicted from active
    active_ids = {s.seg_id for s in bus.active_segments}
    assert needle_id not in active_ids

    # Needle should be findable via search_evicted
    results = bus.search_evicted("port must be 9876")
    assert len(results) >= 1
    assert any(s.seg_id == needle_id for s in results)


def test_evicted_segment_searchable_after_cold_cascade():
    """Evicted segments cascade to cold and remain searchable."""
    from ctx_rm.core.embedding import HashingEmbeddingProvider

    store = TieredStore(
        warm_max_items=1,  # Tiny warm → cascades to cold immediately
        embedding_provider=HashingEmbeddingProvider(),
    )
    bus = ContextBus(
        token_budget=200, store=store, policy=LRUPolicy(), headroom_ratio=0.2
    )

    needle = _make_seg(content="CRITICAL: port must be 9876", tokens=100)
    needle.source = "needle:N1"
    bus.ingest(needle)
    needle_id = needle.seg_id

    # Evict needle and a filler (warm_max_items=1 → needle cascades to cold)
    bus.ingest(_make_seg(content="filler A", tokens=100))
    bus.ingest(_make_seg(content="filler B", tokens=100))

    # Needle should be in cold (warm only holds 1 item)
    assert store.cold.count >= 1

    # Search finds it in cold
    results = bus.search_evicted("port must be 9876")
    assert len(results) >= 1
    assert any(s.seg_id == needle_id for s in results)


def test_recall_by_search_restores_to_active():
    """Search for evicted content, recall by ID, verify back in active."""
    from ctx_rm.core.embedding import HashingEmbeddingProvider

    store = TieredStore(embedding_provider=HashingEmbeddingProvider())
    bus = ContextBus(
        token_budget=300, store=store, policy=LRUPolicy(), headroom_ratio=0.2
    )

    needle = _make_seg(content="CRITICAL: port must be 9876", tokens=50)
    needle.source = "needle:N1"
    needle.metadata = {
        "openai_message": {"role": "user", "content": "[context] port must be 9876"},
    }
    bus.ingest(needle)
    needle_id = needle.seg_id

    # Force eviction
    bus.ingest(_make_seg(content="filler A", tokens=150))
    bus.ingest(_make_seg(content="filler B", tokens=150))

    assert needle_id not in {s.seg_id for s in bus.active_segments}

    # Search → find → recall
    results = bus.search_evicted("port must be 9876")
    assert len(results) >= 1

    recalled = bus.recall(results[0].seg_id)
    assert recalled is not None
    assert recalled.seg_id == needle_id
    assert recalled.seg_id in {s.seg_id for s in bus.active_segments}
    assert recalled.recalled_at is not None


# ── Adaptive batch eviction ─────────────────────────────────────────────


def test_fixed_batch_mode_requests_full_token_delta():
    store = TieredStore()
    policy = RecordingPolicy()
    bus = ContextBus(
        token_budget=1000,
        store=store,
        policy=policy,
        headroom_ratio=0.15,
        eviction_batch_mode="fixed",
    )

    bus.ingest(_make_seg(content="a", tokens=300))
    bus.ingest(_make_seg(content="b", tokens=300))
    bus.ingest(_make_seg(content="c", tokens=300))

    # active=900, target=850 -> fixed mode requests full 50-token delta once
    assert policy.calls == [50]


def test_adaptive_batch_mode_uses_single_evict_near_budget():
    store = TieredStore()
    policy = RecordingPolicy()
    bus = ContextBus(
        token_budget=1000,
        store=store,
        policy=policy,
        headroom_ratio=0.15,
        eviction_batch_mode="adaptive",
        adaptive_single_evict_max_utilization=1.0,
    )

    bus.ingest(_make_seg(content="a", tokens=300))
    bus.ingest(_make_seg(content="b", tokens=300))
    bus.ingest(_make_seg(content="c", tokens=300))

    # active=900 (90% util) -> adaptive mode should request 1 token to force
    # one-at-a-time eviction + re-score.
    assert policy.calls
    assert policy.calls[0] == 1


def test_adaptive_batch_mode_batches_when_far_over_budget():
    store = TieredStore()
    policy = RecordingPolicy()
    bus = ContextBus(
        token_budget=1000,
        store=store,
        policy=policy,
        headroom_ratio=0.15,
        eviction_batch_mode="adaptive",
        adaptive_single_evict_max_utilization=1.0,
    )

    # active=1200, target=850 -> far over budget, adaptive mode should request
    # full delta in a batch step.
    bus.ingest(_make_seg(content="oversize", tokens=1200))

    assert policy.calls
    assert policy.calls[0] == 350
