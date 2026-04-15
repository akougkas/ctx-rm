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
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import numpy as np
import structlog

from ctx_rm.core.embedding import EmbeddingProvider, cosine_similarity_batch
from ctx_rm.core.segment import Segment, Tier

logger = structlog.get_logger()


class StoreWriteError(RuntimeError):
    """Raised when a ColdStore write fails and the transaction was rolled back.

    Callers (ContextBus, TieredStore) should treat this as a durable-storage
    failure — the segment was not persisted and audit state is consistent
    with the last successful commit.
    """


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
        while len(self._store) > self.max_items or self._total_tokens > self.max_tokens:
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
        # WAL mode gives safer concurrent readers + faster durable commits on
        # file-backed stores. It is a no-op for :memory: (ignored by SQLite).
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        self._embedding_dim_warned: bool = False
        self._init_schema()

    @contextmanager
    def _transaction(self, op: str, **ctx: object) -> Iterator[sqlite3.Connection]:
        """Execute a write inside an explicit transaction with rollback on failure.

        On any sqlite3 error the transaction is rolled back and a StoreWriteError
        is raised so callers can decide how to handle the loss. Successful paths
        commit exactly once.
        """
        try:
            yield self._conn
        except sqlite3.Error as exc:
            try:
                self._conn.rollback()
            except sqlite3.Error:
                logger.exception("coldstore_rollback_failed", op=op, **ctx)
            logger.error("coldstore_write_failed", op=op, error=str(exc), **ctx)
            raise StoreWriteError(f"cold store {op} failed: {exc}") from exc
        else:
            try:
                self._conn.commit()
            except sqlite3.Error as exc:
                with suppress(sqlite3.Error):
                    self._conn.rollback()
                logger.error("coldstore_commit_failed", op=op, error=str(exc), **ctx)
                raise StoreWriteError(f"cold store {op} commit failed: {exc}") from exc

    def _init_schema(self) -> None:
        with self._transaction("init_schema"):
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

            # Embedding columns (idempotent migration)
            columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(segments)").fetchall()
            }
            if "embedding" not in columns:
                self._conn.execute("ALTER TABLE segments ADD COLUMN embedding BLOB")
            if "embedding_provider" not in columns:
                self._conn.execute("ALTER TABLE segments ADD COLUMN embedding_provider TEXT")

    def persist(self, seg: Segment) -> None:
        """Write a segment to cold storage, computing embedding if provider set.

        Raises:
            StoreWriteError: if the SQLite write fails. Callers should treat
                this as a durable-storage failure and avoid removing the segment
                from the caller-owned tier.
        """
        seg.tier = Tier.COLD

        embedding_blob = None
        provider_name = None
        if self._embedding_provider is not None:
            vec = self._embedding_provider.embed(seg.content)
            if np.linalg.norm(vec) > 0:
                embedding_blob = vec.astype(np.float32).tobytes()
                provider_name = self._embedding_provider.name

        with self._transaction("persist", seg_id=seg.seg_id):
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

    def _search_by_embedding(self, query: str, top_k: int, threshold: float) -> list[Segment]:
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
        dim_mismatch_count = 0
        for row in rows:
            vec = np.frombuffer(row["embedding"], dtype=np.float32)
            if vec.shape[0] != expected_dim:
                dim_mismatch_count += 1
                continue  # dimension mismatch — skip (provider changed or pre-migration)
            seg_ids.append(row["seg_id"])
            embeddings.append(vec)

        if dim_mismatch_count and not self._embedding_dim_warned:
            logger.warning(
                "coldstore_embedding_dim_mismatch",
                expected_dim=expected_dim,
                skipped=dim_mismatch_count,
                total=len(rows),
                provider=self._embedding_provider.name,  # type: ignore[union-attr]
                hint=(
                    "embedding provider changed mid-session; rebuild the cold "
                    "store or re-embed existing rows to restore recall quality"
                ),
            )
            self._embedding_dim_warned = True

        if not embeddings:
            return self._search_by_keyword(query, top_k)

        stored_matrix = np.stack(embeddings)
        similarities = cosine_similarity_batch(query_vec, stored_matrix)

        # Sort by similarity descending, filter by threshold, take top_k
        ranked = sorted(zip(seg_ids, similarities, strict=True), key=lambda x: x[1], reverse=True)
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
        """Move a segment to graveyard (mark as archived).

        Raises StoreWriteError on commit failure.
        """
        with self._transaction("archive", seg_id=seg_id):
            self._conn.execute(
                "UPDATE segments SET archived = 1, tier = ? WHERE seg_id = ?",
                (Tier.GRAVEYARD.value, seg_id),
            )

    def remove(self, seg_id: str) -> Segment | None:
        """Remove from cold (for recall to active).

        If the retrieval succeeds but the DELETE fails, the transaction rolls
        back and StoreWriteError is raised so the caller does not promote a
        segment that still lives on disk.
        """
        seg = self.retrieve(seg_id)
        if seg is None:
            return None
        with self._transaction("remove", seg_id=seg_id):
            self._conn.execute("DELETE FROM segments WHERE seg_id = ?", (seg_id,))
        return seg

    def log_transition(
        self, seg_id: str, from_tier: str, to_tier: str, reason: str | None, policy: str | None
    ) -> None:
        """Record a tier transition in the audit log.

        Audit writes are best-effort: a commit failure logs the error but does
        not raise, because the parent tier transition may already have
        succeeded and losing a log line is preferable to crashing eviction.
        """
        try:
            with self._transaction(
                "log_transition", seg_id=seg_id, from_tier=from_tier, to_tier=to_tier
            ):
                self._conn.execute(
                    """INSERT INTO eviction_log
                       (seg_id, from_tier, to_tier, reason, policy, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (seg_id, from_tier, to_tier, reason, policy, time.time()),
                )
        except StoreWriteError:
            # Audit-only: swallow so eviction proceeds. Error is already logged.
            pass

    @property
    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM segments WHERE archived = 0").fetchone()
        return row[0] if row else 0

    @property
    def archived_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM segments WHERE archived = 1").fetchone()
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
        """Stage a segment for recall. Returns oldest if queue overflows.

        Overflow is logged at WARNING level so operators can see when the
        recall staging area is thrashing (typical cause: recall fan-out
        exceeds max_items under hot reload).
        """
        seg.tier = Tier.ZOMBIE
        overflow = None
        if len(self._queue) >= self.max_items:
            overflow = self._queue.popleft()
            self._index.pop(overflow.seg_id, None)
            logger.warning(
                "zombie_queue_overflow",
                max_items=self.max_items,
                dropped_seg_id=overflow.seg_id,
                dropped_source=overflow.source,
            )
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
        """Move a segment from Active into the Warm tier.

        Warm insertion is in-memory and always succeeds. If Warm overflows,
        the oldest segments cascade into Cold. A cold-write failure logs and
        re-raises StoreWriteError so callers can surface the durability loss
        without losing the segments currently sitting in Warm.
        """
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
        Cold recalls pass through Zombie staging so validation can reject
        noisy page faults before they reach Active. Returns None on a miss
        across every tier.
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

        Warm is searched by word overlap (any query word in content).
        Cold is searched by embedding similarity (or keyword fallback).
        Results are merged and deduplicated, warm matches ranked by overlap.
        """
        # Extract meaningful query words (3+ chars to skip noise)
        query_words = {w for w in query.lower().split() if len(w) >= 3}

        results: list[Segment] = []
        seen: set[str] = set()

        # Search warm (word overlap on content)
        warm_scored: list[tuple[int, Segment]] = []
        for seg in self.warm._store.values():
            content_lower = seg.content.lower()
            overlap = sum(1 for w in query_words if w in content_lower)
            if overlap > 0:
                warm_scored.append((overlap, seg))

        # Sort by overlap descending
        warm_scored.sort(key=lambda x: x[0], reverse=True)
        for _, seg in warm_scored:
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
        """Move a segment from warm to cold (persistent store).

        If the cold write fails, the segment is re-queued at the head of Warm
        so it survives until the next eviction cycle. This trades a bit of
        memory pressure for durability across transient SQLite errors.
        """
        old_tier = seg.tier.value
        try:
            self.cold.persist(seg)
        except StoreWriteError:
            # Re-insert so the segment stays available; overflow handling
            # will retry on the next eviction.
            logger.warning(
                "cold_persist_retry_via_warm",
                seg_id=seg.seg_id,
                source=seg.source,
            )
            self.warm.put(seg)
            raise
        self.cold.log_transition(seg.seg_id, old_tier, Tier.COLD.value, "warm_age_out", None)
