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

    INTERVAL = "interval"  # Fixed time interval
    THRESHOLD = "threshold"  # When token usage exceeds threshold
    TURN = "turn"  # After every N turns
    HYBRID = "hybrid"  # Combination of all above


class WatcherConfig:
    """Configuration for the background watcher."""

    def __init__(
        self,
        mode: TriggerMode = TriggerMode.HYBRID,
        interval_seconds: float = 5.0,
        threshold_ratio: float = 0.70,  # Trigger at 70% utilization
        turns_interval: int = 3,  # Every 3 turns
        min_tokens_to_evict: int = 1000,  # Don't bother for tiny amounts
        max_consecutive_failures: int = 5,
    ) -> None:
        self.mode = mode
        self.interval_seconds = interval_seconds
        self.threshold_ratio = threshold_ratio
        self.turns_interval = turns_interval
        self.min_tokens_to_evict = min_tokens_to_evict
        self.max_consecutive_failures = max_consecutive_failures


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
        self._stop_event = asyncio.Event()
        self._last_turn: int = 0
        self._cycles_run: int = 0
        self._consecutive_failures: int = 0
        self._total_failures: int = 0
        self._aborted: bool = False

    async def run(self) -> None:
        """Main watcher loop — runs until stop() is called.

        Failures are logged at ERROR level and counted. After
        `config.max_consecutive_failures` failures the watcher aborts so a
        broken background loop cannot silently coexist with a live agent.
        Call `get_stats()` to observe failure counters.
        """
        logger.info(
            "watcher_started",
            mode=self.config.mode.value,
            interval=self.config.interval_seconds,
            max_consecutive_failures=self.config.max_consecutive_failures,
        )

        while not self._stop_event.is_set():
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
                    self._consecutive_failures = 0

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.config.interval_seconds,
                    )
                except TimeoutError:
                    pass  # Normal: timeout = interval elapsed, loop continues
            except asyncio.CancelledError:
                break
            except Exception:
                self._consecutive_failures += 1
                self._total_failures += 1
                logger.exception(
                    "watcher_error",
                    consecutive_failures=self._consecutive_failures,
                    total_failures=self._total_failures,
                )
                if self._consecutive_failures >= self.config.max_consecutive_failures:
                    self._aborted = True
                    logger.error(
                        "watcher_aborted_after_failures",
                        consecutive_failures=self._consecutive_failures,
                        total_failures=self._total_failures,
                    )
                    break
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.config.interval_seconds,
                    )
                except TimeoutError:
                    pass

        logger.info(
            "watcher_stopped",
            total_cycles=self._cycles_run,
            aborted=self._aborted,
            total_failures=self._total_failures,
        )

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._stop_event.set()

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
            "running": not self._stop_event.is_set() and not self._aborted,
            "aborted": self._aborted,
            "cycles_run": self._cycles_run,
            "consecutive_failures": self._consecutive_failures,
            "total_failures": self._total_failures,
            "mode": self.config.mode.value,
            "last_turn_checked": self._last_turn,
        }
