"""Tests for the TieredStore (graveyard architecture)."""

import numpy as np

from ctx_rm.core.embedding import HashingEmbeddingProvider
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


# ── ColdStore Embedding Search ────────────────────────────────────────


def _make_cold_store_with_embeddings():
    provider = HashingEmbeddingProvider()
    return ColdStore(embedding_provider=provider), provider


def test_cold_store_persist_stores_embedding():
    store, _provider = _make_cold_store_with_embeddings()
    seg = _make_seg("python authentication handler")
    store.persist(seg)

    row = store._conn.execute(
        "SELECT embedding, embedding_provider FROM segments WHERE seg_id = ?",
        (seg.seg_id,),
    ).fetchone()

    assert row["embedding"] is not None
    assert row["embedding_provider"] == "hashing"
    vec = np.frombuffer(row["embedding"], dtype=np.float32)
    assert vec.shape == (256,)


def test_cold_store_search_by_embedding_similarity():
    store, _ = _make_cold_store_with_embeddings()
    store.persist(_make_seg("python authentication handler"))
    store.persist(_make_seg("python auth middleware validation"))
    store.persist(_make_seg("sql database migration schema"))

    results = store.search("python auth")
    assert len(results) >= 2
    # Auth-related segments should rank above database migration
    contents = [r.content for r in results]
    auth_indices = [i for i, c in enumerate(contents) if "auth" in c]
    db_indices = [i for i, c in enumerate(contents) if "database" in c or "migration" in c]
    if db_indices:
        assert min(auth_indices) < min(db_indices)


def test_cold_store_search_fallback_no_provider():
    store = ColdStore()  # No embedding_provider
    store.persist(_make_seg("auth handler code"))
    store.persist(_make_seg("database migration"))

    results = store.search("auth")
    assert len(results) == 1
    assert "auth" in results[0].content


def test_cold_store_search_threshold_filters():
    store, _ = _make_cold_store_with_embeddings()
    store.persist(_make_seg("python authentication handler"))
    store.persist(_make_seg("python auth middleware validation"))
    store.persist(_make_seg("sql database migration schema"))

    all_results = store.search("python auth", threshold=0.0)
    high_threshold_results = store.search("python auth", threshold=0.99)
    assert len(high_threshold_results) <= len(all_results)


def test_cold_store_search_top_k_limits_results():
    store, _ = _make_cold_store_with_embeddings()
    for i in range(5):
        store.persist(_make_seg(f"python auth handler variant {i}"))

    results = store.search("python auth", top_k=2)
    assert len(results) <= 2


def test_cold_store_empty_content_embedding():
    store, _ = _make_cold_store_with_embeddings()
    seg = _make_seg("x")
    # Should not raise
    store.persist(seg)
    # Embedding may be NULL for very short/zero-norm content, or may have a value
    row = store._conn.execute(
        "SELECT embedding FROM segments WHERE seg_id = ?", (seg.seg_id,)
    ).fetchone()
    # Just verify no crash — embedding can be NULL or valid BLOB
    assert row is not None


def test_cold_store_schema_migration_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    provider = HashingEmbeddingProvider()

    store1 = ColdStore(db_path=db_path, embedding_provider=provider)
    store1.persist(_make_seg("first run"))
    store1.close()

    # Second open should not error (columns already exist)
    store2 = ColdStore(db_path=db_path, embedding_provider=provider)
    store2.persist(_make_seg("second run"))
    assert store2.count == 2
    store2.close()
