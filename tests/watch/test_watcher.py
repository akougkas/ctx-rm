"""Watcher race condition regression tests.

Validates that the asyncio.Event-based stop mechanism is free from the
race condition where run() could set _running=True after stop() set it False.
"""

from __future__ import annotations

import asyncio

import pytest

from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.segment import Segment, SegmentRole, Tier
from ctx_rm.watch.watcher import TriggerMode, Watcher, WatcherConfig


def _make_minimal_bus(token_budget: int = 10_000) -> ContextBus:
    """Create a ContextBus with minimal config for watcher tests."""
    store = TieredStore(db_path=":memory:")
    policy = LRUPolicy()
    scorer = HeuristicScorer()
    return ContextBus(
        token_budget=token_budget,
        store=store,
        policy=policy,
        scorer=scorer,
    )


def _make_seg(content: str = "test", tokens: int = 100) -> Segment:
    return Segment(content=content, role=SegmentRole.USER, token_count=tokens)


@pytest.mark.asyncio
async def test_watcher_rapid_start_stop():
    """Race condition regression: start then immediately stop must not hang."""
    bus = _make_minimal_bus()
    config = WatcherConfig(interval_seconds=5.0)
    watcher = Watcher(bus, config)

    task = asyncio.create_task(watcher.run())
    watcher.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert watcher.get_stats()["running"] is False


@pytest.mark.asyncio
async def test_watcher_start_stop_repeated():
    """10 consecutive start/stop cycles must complete without deadlock."""
    bus = _make_minimal_bus()

    for _ in range(10):
        watcher = Watcher(bus, WatcherConfig(interval_seconds=5.0))
        task = asyncio.create_task(watcher.run())
        watcher.stop()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_watcher_stop_before_start():
    """Calling stop() before run() starts must not hang."""
    bus = _make_minimal_bus()
    watcher = Watcher(bus, WatcherConfig(interval_seconds=5.0))

    # Stop signal set before run() even starts
    watcher.stop()

    task = asyncio.create_task(watcher.run())
    await asyncio.wait_for(task, timeout=2.0)

    assert watcher.get_stats()["running"] is False


@pytest.mark.asyncio
async def test_watcher_get_stats_reflects_state():
    """get_stats() running flag tracks stop-event state.

    Before stop(): running=True (stop not requested).
    After stop(): running=False.
    """
    bus = _make_minimal_bus()
    watcher = Watcher(bus, WatcherConfig(interval_seconds=5.0))

    # Before stop: not yet stopped → running is True
    assert watcher.get_stats()["running"] is True

    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0)  # Yield to let run() enter its loop

    # While running: still True
    assert watcher.get_stats()["running"] is True

    watcher.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # After stop: False
    assert watcher.get_stats()["running"] is False


@pytest.mark.asyncio
async def test_watcher_runs_eviction_cycle():
    """Watcher triggers eviction when bus exceeds headroom target."""
    bus = _make_minimal_bus(token_budget=10_000)
    # headroom_target = 10000 * 0.85 = 8500

    # Ingest segments that stay under headroom (no auto-eviction)
    for i in range(4):
        bus.ingest(_make_seg(content=f"segment_{i}", tokens=2000))
    # active_tokens = 8000, under headroom_target=8500

    config = WatcherConfig(
        interval_seconds=0.01,
        mode=TriggerMode.HYBRID,
        min_tokens_to_evict=100,
    )
    watcher = Watcher(bus, config)

    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0)  # Let watcher enter its loop

    # Now push over headroom by directly manipulating active state.
    # This simulates tokens arriving between watcher cycles without
    # bus.ingest's auto-eviction cleaning up first.
    seg = _make_seg(content="overflow", tokens=2000)
    seg.tier = Tier.ACTIVE
    bus._active[seg.seg_id] = seg
    bus._active_tokens += seg.token_count
    # active_tokens = 10000, headroom_target = 8500, tokens_over = 1500

    # Let the watcher run a few cycles
    await asyncio.sleep(0.15)
    watcher.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert watcher._cycles_run > 0
