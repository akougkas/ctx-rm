"""Concurrency and idempotency tests for ContextBus."""

from __future__ import annotations

import threading

from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.segment import Segment, SegmentRole


def _seg(i: int, tokens: int = 10) -> Segment:
    return Segment(
        content=f"payload {i}",
        role=SegmentRole.USER,
        token_count=tokens,
        source="user_task",
    )


def _make_bus(budget: int = 5_000) -> ContextBus:
    return ContextBus(
        token_budget=budget,
        store=TieredStore(),
        policy=LRUPolicy(),
        headroom_ratio=0.1,
    )


class TestAdvanceTurnIdempotency:
    def test_explicit_turn_is_idempotent(self) -> None:
        bus = _make_bus()
        bus.advance_turn(turn_number=5)
        bus.advance_turn(turn_number=5)  # no-op
        bus.advance_turn(turn_number=5)  # no-op
        assert bus.turn_number == 5

    def test_explicit_turn_advances(self) -> None:
        bus = _make_bus()
        bus.advance_turn(turn_number=3)
        assert bus.turn_number == 3
        bus.advance_turn(turn_number=7)
        assert bus.turn_number == 7

    def test_no_arg_increments(self) -> None:
        bus = _make_bus()
        bus.advance_turn()
        bus.advance_turn()
        assert bus.turn_number == 2


class TestBusThreadSafety:
    def test_concurrent_ingest_preserves_token_sum(self) -> None:
        bus = _make_bus(budget=1_000_000)
        per_thread = 50
        num_threads = 8

        def worker(base: int) -> None:
            for i in range(per_thread):
                bus.ingest(_seg(base * per_thread + i, tokens=10))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert bus.active_tokens == num_threads * per_thread * 10
        assert len(bus.active_segments) == num_threads * per_thread
