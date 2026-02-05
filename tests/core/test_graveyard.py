"""Tests for the TieredStore (graveyard architecture)."""

from ctx_rm.core.graveyard import ColdStore, TieredStore, WarmCache, ZombieQueue
from ctx_rm.core.segment import Segment, SegmentRole, Tier


def _make_seg(content: str = "test", tokens: int = 100) -> Segment:
    return Segment(content=content, role=SegmentRole.TOOL, token_count=tokens)


# ── WarmCache ───────────────────────────────────────────────────────────


def test_warm_cache_put_and_get():
    cache = WarmCache(max_items=3)
    seg = _make_seg("hello")
    cache.put(seg)
    assert cache.get(seg.seg_id) is not None
    assert cache.count == 1


def test_warm_cache_lru_eviction():
    cache = WarmCache(max_items=2)
    s1 = _make_seg("first", tokens=50)
    s2 = _make_seg("second", tokens=50)
    s3 = _make_seg("third", tokens=50)

    cache.put(s1)
    cache.put(s2)
    aged = cache.put(s3)  # s1 should be aged out

    assert len(aged) == 1
    assert aged[0].seg_id == s1.seg_id
    assert cache.count == 2


def test_warm_cache_token_limit():
    cache = WarmCache(max_items=100, max_tokens=150)
    s1 = _make_seg("big", tokens=100)
    s2 = _make_seg("also big", tokens=100)

    cache.put(s1)
    aged = cache.put(s2)

    assert len(aged) == 1  # s1 aged out due to token limit


# ── ColdStore ───────────────────────────────────────────────────────────


def test_cold_store_persist_and_retrieve():
    store = ColdStore()
    seg = _make_seg("persisted")
    store.persist(seg)

    retrieved = store.retrieve(seg.seg_id)
    assert retrieved is not None
    assert retrieved.content == "persisted"
    assert retrieved.tier == Tier.COLD


def test_cold_store_search():
    store = ColdStore()
    store.persist(_make_seg("auth handler code"))
    store.persist(_make_seg("database migration"))
    store.persist(_make_seg("auth middleware"))

    results = store.search("auth")
    assert len(results) == 2


def test_cold_store_archive():
    store = ColdStore()
    seg = _make_seg("to archive")
    store.persist(seg)
    store.archive(seg.seg_id)

    # Should not appear in normal retrieval
    assert store.retrieve(seg.seg_id) is None
    assert store.archived_count == 1


# ── ZombieQueue ─────────────────────────────────────────────────────────


def test_zombie_queue_stage_and_promote():
    queue = ZombieQueue(max_items=4)
    seg = _make_seg("zombie")
    queue.stage(seg)
    assert queue.count == 1

    promoted = queue.promote(seg.seg_id)
    assert promoted is not None
    assert queue.count == 0


def test_zombie_queue_overflow():
    queue = ZombieQueue(max_items=2)
    s1 = _make_seg("z1")
    s2 = _make_seg("z2")
    s3 = _make_seg("z3")

    queue.stage(s1)
    queue.stage(s2)
    overflow = queue.stage(s3)

    assert overflow is not None
    assert overflow.seg_id == s1.seg_id
    assert queue.count == 2


# ── TieredStore (full flow) ─────────────────────────────────────────────


def test_tiered_store_demote_to_warm():
    store = TieredStore()
    seg = _make_seg("evicted")
    seg.evict(reason="test", policy="test")
    store.demote_to_warm(seg)

    assert store.warm.count == 1
    assert seg.tier == Tier.WARM


def test_tiered_store_recall_from_warm():
    store = TieredStore()
    seg = _make_seg("recallable")
    seg.evict(reason="test", policy="test")
    store.demote_to_warm(seg)

    recalled = store.recall(seg.seg_id)
    assert recalled is not None
    assert recalled.content == "recallable"


def test_tiered_store_warm_to_cold_cascade():
    store = TieredStore(warm_max_items=2)
    segs = [_make_seg(f"seg_{i}") for i in range(4)]

    for seg in segs:
        seg.evict(reason="test", policy="test")
        store.demote_to_warm(seg)

    # First 2 should have cascaded to cold
    assert store.warm.count == 2
    assert store.cold.count == 2


def test_tiered_store_recall_from_cold():
    store = TieredStore(warm_max_items=1)
    s1 = _make_seg("first")
    s2 = _make_seg("second")

    s1.evict(reason="test", policy="test")
    store.demote_to_warm(s1)
    s2.evict(reason="test", policy="test")
    store.demote_to_warm(s2)  # s1 cascades to cold

    recalled = store.recall(s1.seg_id)
    assert recalled is not None
    assert recalled.content == "first"


def test_tiered_store_stats():
    store = TieredStore()
    stats = store.get_stats()
    assert stats["warm_count"] == 0
    assert stats["cold_count"] == 0
