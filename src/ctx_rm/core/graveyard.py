"""TieredStore: multi-tier memory with OS virtual memory semantics.

Tier transitions follow OS/DB buffer pool patterns:
  Active → Warm  (eviction — like buffer pool eviction to OS page cache)
  Warm   → Cold  (age-out — like page cache writeback to disk)
  Cold   → Graveyard (archive — like WAL archival)

Recall path (page fault):
  Cold/Graveyard → Zombie → Active (rehydration with validation)
  Warm           → Active (fast promote, like ARC ghost hit)

Inspired by PostgreSQL's clock-sweep buffer, MySQL InnoDB's split LRU,
and ARC's ghost lists (B1/B2).

See docs/tiered_graveyard.md for the theoretical foundation.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import OrderedDict, deque
from pathlib import Path

import numpy as np
import structlog

from ctx_rm.core.embedding import EmbeddingProvider, cosine_similarity_batch
from ctx_rm.core.segment import Segment, Tier

logger = structlog.get_logger()


class WarmCache:
    """Recently evicted segments — fast in-memory recall.

    Analogous to the OS page cache or ARC's ghost list.
    Uses LRU eviction when capacity is exceeded.
    """

    def __init__(self, max_items: int = 64, max_tokens: int = 50_000) -> None:
        self.max_items = max_items
        self.max_tokens = max_tokens
        self._store: OrderedDict[str, Segment] = OrderedDict()
        self._total_tokens: int = 0

    def put(self, seg: Segment) -> list[Segment]:
        """Add a segment. Returns any segments aged out to cold."""
        seg.tier = Tier.WARM
        self._store[seg.seg_id] = seg
        self._store.move_to_end(seg.seg_id)
        self._total_tokens += seg.token_count

        aged_out: list[Segment] = []
        while (
            len(self._store) > self.max_items or self._total_tokens > self.max_tokens
        ):
            _, evicted = self._store.popitem(last=False)
            self._total_tokens -= evicted.token_count
            aged_out.append(evicted)

        return aged_out

    def get(self, seg_id: str) -> Segment | None:
        """Retrieve and promote (move to end of LRU)."""
        if seg_id in self._store:
            self._store.move_to_end(seg_id)
            return self._store[seg_id]
        return None

    def remove(self, seg_id: str) -> Segment | None:
        """Remove a segment (for promotion to active)."""
        if seg_id in self._store:
            seg = self._store.pop(seg_id)
            self._total_tokens -= seg.token_count
            return seg
        return None

    @property
    def count(self) -> int:
        return len(self._store)

    @property
    def total_tokens(self) -> int:
        return self._total_tokens


class ColdStore:
    """Persistent storage for evicted segments — SQLite-backed.

    Analogous to database disk pages. Supports keyword search and
    metadata-based retrieval. Embedding-based search is pluggable.
    """

    def __init__(
        self,
        db_path: Path | str = ":memory:",
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._embedding_provider = embedding_provider
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS segments (
                seg_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                role TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                created_at REAL NOT NULL,
                evicted_at REAL,
                last_accessed REAL,
                access_count INTEGER DEFAULT 0,
                relevance_score REAL,
                eviction_reason TEXT,
                eviction_policy TEXT,
                source TEXT,
                turn_number INTEGER,
                summary TEXT,
                metadata_json TEXT,
                tier TEXT DEFAULT 'cold',
                archived INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_seg_turn ON segments(turn_number);
            CREATE INDEX IF NOT EXISTS idx_seg_source ON segments(source);
            CREATE INDEX IF NOT EXISTS idx_seg_tier ON segments(tier);

            -- Audit log: every eviction event
            CREATE TABLE IF NOT EXISTS eviction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seg_id TEXT NOT NULL,
                from_tier TEXT NOT NULL,
                to_tier TEXT NOT NULL,
                reason TEXT,
                policy TEXT,
                timestamp REAL NOT NULL
            );
        """)
        self._conn.commit()

        # Embedding columns (idempotent migration)
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(segments)").fetchall()}
        if "embedding" not in columns:
            self._conn.execute("ALTER TABLE segments ADD COLUMN embedding BLOB")
        if "embedding_provider" not in columns:
            self._conn.execute("ALTER TABLE segments ADD COLUMN embedding_provider TEXT")
        self._conn.commit()

    def persist(self, seg: Segment) -> None:
        """Write a segment to cold storage, computing embedding if provider set."""
        seg.tier = Tier.COLD

        embedding_blob = None
        provider_name = None
        if self._embedding_provider is not None:
            vec = self._embedding_provider.embed(seg.content)
            if np.linalg.norm(vec) > 0:
                embedding_blob = vec.astype(np.float32).tobytes()
                provider_name = self._embedding_provider.name

        self._conn.execute(
            """INSERT OR REPLACE INTO segments
               (seg_id, content, role, token_count, created_at, evicted_at,
                last_accessed, access_count, relevance_score, eviction_reason,
                eviction_policy, source, turn_number, summary, metadata_json,
                tier, embedding, embedding_provider)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                seg.seg_id,
                seg.content,
                seg.role.value,
                seg.token_count,
                seg.created_at,
                seg.evicted_at,
                seg.last_accessed,
                seg.access_count,
                seg.relevance_score,
                seg.eviction_reason,
                seg.eviction_policy,
                seg.source,
                seg.turn_number,
                seg.summary,
                json.dumps(seg.metadata) if seg.metadata else None,
                Tier.COLD.value,
                embedding_blob,
                provider_name,
            ),
        )
        self._conn.commit()

    def retrieve(self, seg_id: str) -> Segment | None:
        """Retrieve a specific segment by ID."""
        row = self._conn.execute(
            "SELECT * FROM segments WHERE seg_id = ? AND archived = 0", (seg_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_segment(row)

    def search(self, query: str, top_k: int = 5, threshold: float = 0.0) -> list[Segment]:
        """Search cold storage -- cosine similarity or keyword LIKE fallback."""
        if self._embedding_provider is not None:
            return self._search_by_embedding(query, top_k, threshold)
        return self._search_by_keyword(query, top_k)

    def _search_by_keyword(self, query: str, top_k: int) -> list[Segment]:
        """Keyword LIKE search — fallback when no embedding provider."""
        rows = self._conn.execute(
            """SELECT * FROM segments
               WHERE archived = 0 AND content LIKE ?
               ORDER BY relevance_score DESC NULLS LAST, evicted_at DESC
               LIMIT ?""",
            (f"%{query}%", top_k),
        ).fetchall()
        return [self._row_to_segment(r) for r in rows]

    def _search_by_embedding(
        self, query: str, top_k: int, threshold: float
    ) -> list[Segment]:
        """Cosine similarity search using embedding provider."""
        query_vec = self._embedding_provider.embed(query)  # type: ignore[union-attr]
        if np.linalg.norm(query_vec) == 0:
            return self._search_by_keyword(query, top_k)

        rows = self._conn.execute(
            """SELECT seg_id, embedding FROM segments
               WHERE archived = 0 AND embedding IS NOT NULL AND LENGTH(embedding) > 0"""
        ).fetchall()

        if not rows:
            return self._search_by_keyword(query, top_k)

        expected_dim = self._embedding_provider.dimensions  # type: ignore[union-attr]
        seg_ids: list[str] = []
        embeddings: list[np.ndarray] = []
        for row in rows:
            vec = np.frombuffer(row["embedding"], dtype=np.float32)
            if vec.shape[0] != expected_dim:
                continue  # dimension mismatch — skip (provider changed or pre-migration)
            seg_ids.append(row["seg_id"])
            embeddings.append(vec)

        if not embeddings:
            return self._search_by_keyword(query, top_k)

        stored_matrix = np.stack(embeddings)
        similarities = cosine_similarity_batch(query_vec, stored_matrix)

        # Sort by similarity descending, filter by threshold, take top_k
        ranked = sorted(
            zip(seg_ids, similarities, strict=True), key=lambda x: x[1], reverse=True
        )
        results: list[Segment] = []
        for sid, sim in ranked:
            if sim < threshold:
                break
            seg = self.retrieve(sid)
            if seg is not None:
                results.append(seg)
            if len(results) >= top_k:
                break

        return results

    def archive(self, seg_id: str) -> None:
        """Move a segment to graveyard (mark as archived)."""
        self._conn.execute(
            "UPDATE segments SET archived = 1, tier = ? WHERE seg_id = ?",
            (Tier.GRAVEYARD.value, seg_id),
        )
        self._conn.commit()

    def remove(self, seg_id: str) -> Segment | None:
        """Remove from cold (for recall to active)."""
        seg = self.retrieve(seg_id)
        if seg:
            self._conn.execute("DELETE FROM segments WHERE seg_id = ?", (seg_id,))
            self._conn.commit()
        return seg

    def log_transition(
        self, seg_id: str, from_tier: str, to_tier: str, reason: str | None, policy: str | None
    ) -> None:
        """Record a tier transition in the audit log."""
        self._conn.execute(
            """INSERT INTO eviction_log (seg_id, from_tier, to_tier, reason, policy, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (seg_id, from_tier, to_tier, reason, policy, time.time()),
        )
        self._conn.commit()

    @property
    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM segments WHERE archived = 0"
        ).fetchone()
        return row[0] if row else 0

    @property
    def archived_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM segments WHERE archived = 1"
        ).fetchone()
        return row[0] if row else 0

    def _row_to_segment(self, row: sqlite3.Row) -> Segment:
        from ctx_rm.core.segment import SegmentRole

        return Segment(
            seg_id=row["seg_id"],
            content=row["content"],
            role=SegmentRole(row["role"]),
            token_count=row["token_count"],
            created_at=row["created_at"],
            evicted_at=row["evicted_at"],
            last_accessed=row["last_accessed"] or row["created_at"],
            access_count=row["access_count"] or 0,
            relevance_score=row["relevance_score"],
            eviction_reason=row["eviction_reason"],
            eviction_policy=row["eviction_policy"],
            source=row["source"],
            turn_number=row["turn_number"],
            summary=row["summary"],
            tier=Tier(row["tier"]) if row["tier"] else Tier.COLD,
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )

    def close(self) -> None:
        self._conn.close()


class ZombieQueue:
    """Staging area for segments being recalled — page-fault handling.

    Segments pass through Zombie before re-entering Active. This allows
    validation (relevance check) to prevent thrashing.
    """

    def __init__(self, max_items: int = 16) -> None:
        self.max_items = max_items
        self._queue: deque[Segment] = deque()
        self._index: dict[str, Segment] = {}

    def stage(self, seg: Segment) -> Segment | None:
        """Stage a segment for recall. Returns oldest if queue overflows."""
        seg.tier = Tier.ZOMBIE
        overflow = None
        if len(self._queue) >= self.max_items:
            overflow = self._queue.popleft()
            self._index.pop(overflow.seg_id, None)
        self._queue.append(seg)
        self._index[seg.seg_id] = seg
        return overflow

    def promote(self, seg_id: str) -> Segment | None:
        """Remove from zombie queue (promoting to active)."""
        seg = self._index.pop(seg_id, None)
        if seg:
            self._queue.remove(seg)
        return seg

    @property
    def count(self) -> int:
        return len(self._queue)


class TieredStore:
    """Unified multi-tier storage manager.

    Orchestrates Warm → Cold → Graveyard transitions and the Zombie recall path.
    """

    def __init__(
        self,
        db_path: Path | str = ":memory:",
        warm_max_items: int = 64,
        warm_max_tokens: int = 50_000,
        cold_archive_age: float = 3600.0,  # Archive cold segments after 1 hour
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.warm = WarmCache(max_items=warm_max_items, max_tokens=warm_max_tokens)
        self.cold = ColdStore(db_path=db_path, embedding_provider=embedding_provider)
        self.zombie = ZombieQueue()
        self.cold_archive_age = cold_archive_age

    def demote_to_warm(self, seg: Segment) -> None:
        """First stop after eviction from Active."""
        old_tier = seg.tier.value
        aged_out = self.warm.put(seg)

        self.cold.log_transition(
            seg.seg_id, old_tier, Tier.WARM.value, seg.eviction_reason, seg.eviction_policy
        )

        # Segments aged out of warm go to cold
        for cold_seg in aged_out:
            self._demote_to_cold(cold_seg)

    def recall(self, seg_id: str) -> Segment | None:
        """Attempt to recall a segment from any tier.

        Search order: Warm (fast) → Zombie (staged) → Cold (disk) → Graveyard.
        Recalled segments pass through Zombie staging.
        """
        # Try warm first (fast path — like ARC ghost hit)
        seg = self.warm.remove(seg_id)
        if seg:
            logger.debug("recall_from_warm", seg_id=seg_id)
            return seg

        # Try zombie (already staged)
        seg = self.zombie.promote(seg_id)
        if seg:
            logger.debug("recall_from_zombie", seg_id=seg_id)
            return seg

        # Try cold (disk — page fault)
        seg = self.cold.remove(seg_id)
        if seg:
            logger.debug("recall_from_cold", seg_id=seg_id)
            # Stage through zombie for validation
            overflow = self.zombie.stage(seg)
            if overflow:
                self._demote_to_cold(overflow)
            return self.zombie.promote(seg_id)

        logger.debug("recall_miss", seg_id=seg_id)
        return None

    def search(self, query: str, top_k: int = 5, threshold: float = 0.0) -> list[Segment]:
        """Search across cold storage for matching segments."""
        return self.cold.search(query, top_k=top_k, threshold=threshold)

    def search_all(self, query: str, top_k: int = 5) -> list[Segment]:
        """Search all non-active tiers (warm + cold) for matching segments.

        Warm is searched by keyword substring match.
        Cold is searched by embedding similarity (or keyword fallback).
        Results are merged and deduplicated, warm matches first.
        """
        query_lower = query.lower()
        results: list[Segment] = []
        seen: set[str] = set()

        # Search warm (keyword match on content)
        for seg in self.warm._store.values():
            if query_lower in seg.content.lower():
                results.append(seg)
                seen.add(seg.seg_id)

        # Search cold (embedding or keyword)
        cold_results = self.cold.search(query, top_k=top_k)
        for seg in cold_results:
            if seg.seg_id not in seen:
                results.append(seg)

        return results[:top_k]

    def get_stats(self) -> dict:
        return {
            "warm_count": self.warm.count,
            "warm_tokens": self.warm.total_tokens,
            "cold_count": self.cold.count,
            "graveyard_count": self.cold.archived_count,
            "zombie_count": self.zombie.count,
        }

    def close(self) -> None:
        self.cold.close()

    # ── Internal ────────────────────────────────────────────────────────

    def _demote_to_cold(self, seg: Segment) -> None:
        """Move a segment from warm to cold (persistent store)."""
        old_tier = seg.tier.value
        self.cold.persist(seg)
        self.cold.log_transition(seg.seg_id, old_tier, Tier.COLD.value, "warm_age_out", None)
