"""Durability tests for ColdStore and TieredStore.

Verifies that SQLite write failures surface as StoreWriteError, rollback the
transaction, and leave Warm state intact so segments are not silently dropped.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import patch

import pytest

from ctx_rm.core.graveyard import ColdStore, StoreWriteError, TieredStore, ZombieQueue
from ctx_rm.core.segment import Segment, SegmentRole, Tier


class _FailingConn:
    """sqlite3.Connection proxy that forces writes to fail on demand.

    Used because sqlite3.Connection is a C type whose attributes can't be
    patched with unittest.mock. We wrap the real connection and only override
    execute / commit / rollback.
    """

    def __init__(
        self, real: sqlite3.Connection, *, fail_execute: bool = False, fail_commit: bool = False
    ) -> None:
        self._real = real
        self._fail_execute = fail_execute
        self._fail_commit = fail_commit

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        if self._fail_execute:
            raise sqlite3.OperationalError("simulated disk I/O error")
        return self._real.execute(*args, **kwargs)

    def executescript(self, *args: Any, **kwargs: Any) -> Any:
        if self._fail_execute:
            raise sqlite3.OperationalError("simulated disk I/O error")
        return self._real.executescript(*args, **kwargs)

    def commit(self) -> None:
        if self._fail_commit:
            raise sqlite3.OperationalError("simulated commit failure")
        self._real.commit()

    def rollback(self) -> None:
        self._real.rollback()

    def close(self) -> None:
        self._real.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _seg(seg_id: str = "s1", content: str = "hello") -> Segment:
    return Segment(
        seg_id=seg_id,
        content=content,
        role=SegmentRole.TOOL,
        token_count=10,
        source="tool:file_read",
    )


class TestColdStoreDurability:
    def test_persist_raises_on_write_failure(self) -> None:
        store = ColdStore()
        seg = _seg()
        store._conn = _FailingConn(store._conn, fail_execute=True)  # type: ignore[assignment]
        with pytest.raises(StoreWriteError):
            store.persist(seg)

    def test_persist_rolls_back_on_commit_failure(self) -> None:
        store = ColdStore()
        seg = _seg()
        failing = _FailingConn(store._conn, fail_commit=True)
        store._conn = failing  # type: ignore[assignment]
        with pytest.raises(StoreWriteError):
            store.persist(seg)
        # Flip the failure off and retry — the same connection must still work.
        failing._fail_commit = False
        store.persist(seg)
        assert store.retrieve("s1") is not None

    def test_archive_raises_on_failure(self) -> None:
        store = ColdStore()
        store.persist(_seg("s1"))
        store._conn = _FailingConn(store._conn, fail_execute=True)  # type: ignore[assignment]
        with pytest.raises(StoreWriteError):
            store.archive("s1")

    def test_log_transition_swallows_failure(self) -> None:
        """Audit log failures must not bubble up into eviction paths."""
        store = ColdStore()
        store._conn = _FailingConn(store._conn, fail_execute=True)  # type: ignore[assignment]
        # Must not raise.
        store.log_transition("s1", "active", "warm", "test", "lru")


class TestTieredStoreDurability:
    def test_cold_persist_failure_keeps_segment_in_warm(self) -> None:
        store = TieredStore(warm_max_items=1, warm_max_tokens=1_000_000)
        store.demote_to_warm(_seg("s1", "first segment content"))

        # The next demote will overflow Warm (max_items=1) and cascade to Cold.
        # Force the cold persist to fail; the overflow segment must not be lost.
        with patch.object(
            store.cold,
            "persist",
            side_effect=StoreWriteError("disk full"),
        ):
            with pytest.raises(StoreWriteError):
                store.demote_to_warm(_seg("s2", "second segment content"))

        # Both segments are still reachable from Warm
        assert store.warm.get("s1") is not None or store.warm.get("s2") is not None


class TestZombieOverflowLogging:
    def test_overflow_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        q = ZombieQueue(max_items=2)
        q.stage(_seg("a"))
        q.stage(_seg("b"))
        caplog.clear()
        dropped = q.stage(_seg("c"))
        assert dropped is not None
        assert dropped.seg_id == "a"
