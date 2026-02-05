"""Watcher: async background eviction monitor.

The Watcher runs as an asyncio task alongside the benchmark harness.
It periodically checks the ContextBus and triggers eviction cycles
based on configurable trigger policies.

This is the core of ctx-rm's "background removal" innovation — the
primary agent never blocks on eviction.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any

import structlog

from ctx_rm.core.bus import ContextBus

logger = structlog.get_logger()


class TriggerMode(StrEnum):
    """When the watcher should trigger eviction."""

    INTERVAL = "interval"       # Fixed time interval
    THRESHOLD = "threshold"     # When token usage exceeds threshold
    TURN = "turn"               # After every N turns
    HYBRID = "hybrid"           # Combination of all above


class WatcherConfig:
    """Configuration for the background watcher."""

    def __init__(
        self,
        mode: TriggerMode = TriggerMode.HYBRID,
        interval_seconds: float = 5.0,
        threshold_ratio: float = 0.70,   # Trigger at 70% utilization
        turns_interval: int = 3,         # Every 3 turns
        min_tokens_to_evict: int = 1000, # Don't bother for tiny amounts
    ) -> None:
        self.mode = mode
        self.interval_seconds = interval_seconds
        self.threshold_ratio = threshold_ratio
        self.turns_interval = turns_interval
        self.min_tokens_to_evict = min_tokens_to_evict


class Watcher:
    """Async background watcher that monitors and triggers eviction.

    Usage:
        watcher = Watcher(bus, config)
        task = asyncio.create_task(watcher.run())
        # ... agent does its work ...
        watcher.stop()
        await task
    """

    def __init__(self, bus: ContextBus, config: WatcherConfig | None = None) -> None:
        self.bus = bus
        self.config = config or WatcherConfig()
        self._running = False
        self._last_turn: int = 0
        self._cycles_run: int = 0

    async def run(self) -> None:
        """Main watcher loop — runs until stop() is called."""
        self._running = True
        logger.info(
            "watcher_started",
            mode=self.config.mode.value,
            interval=self.config.interval_seconds,
        )

        while self._running:
            try:
                if self._should_trigger():
                    evicted = self.bus.run_eviction_cycle()
                    if evicted:
                        self._cycles_run += 1
                        logger.info(
                            "watcher_eviction",
                            cycle=self._cycles_run,
                            evicted=len(evicted),
                            tokens_freed=sum(s.token_count for s in evicted),
                        )
                    self._last_turn = self.bus.turn_number

                await asyncio.sleep(self.config.interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("watcher_error")
                await asyncio.sleep(self.config.interval_seconds)

        logger.info("watcher_stopped", total_cycles=self._cycles_run)

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._running = False

    def _should_trigger(self) -> bool:
        """Evaluate trigger conditions based on configured mode."""
        mode = self.config.mode

        utilization = self.bus.active_tokens / self.bus.token_budget if self.bus.token_budget else 0
        tokens_over = self.bus.active_tokens - self.bus.headroom_target
        turns_elapsed = self.bus.turn_number - self._last_turn

        if tokens_over < self.config.min_tokens_to_evict:
            return False

        if mode == TriggerMode.THRESHOLD:
            return utilization >= self.config.threshold_ratio

        if mode == TriggerMode.TURN:
            return turns_elapsed >= self.config.turns_interval

        if mode == TriggerMode.INTERVAL:
            return True  # Checked every interval_seconds by the sleep

        # Hybrid: any condition triggers
        return (
            utilization >= self.config.threshold_ratio
            or turns_elapsed >= self.config.turns_interval
        )

    def get_stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycles_run": self._cycles_run,
            "mode": self.config.mode.value,
            "last_turn_checked": self._last_turn,
        }
