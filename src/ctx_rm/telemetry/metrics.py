"""MetricsCollector: tracks token usage, eviction stats, and recall patterns.

This is a first-class citizen of ctx-rm for evaluation and runtime inspection.
Every event is recorded with timestamps for post-hoc analysis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from ctx_rm.core.segment import Segment

logger = structlog.get_logger()


@dataclass
class TurnSnapshot:
    """Snapshot of system state at a given turn."""

    turn: int
    timestamp: float
    active_tokens: int
    active_segments: int
    warm_count: int
    cold_count: int
    graveyard_count: int
    zombie_count: int
    utilization: float


@dataclass
class EvictionEvent:
    """Record of a single eviction."""

    seg_id: str
    turn: int
    timestamp: float
    tokens: int
    reason: str
    policy: str
    age_seconds: float
    idle_seconds: float
    composite_score: float | None
    source: str | None = None


@dataclass
class RecallEvent:
    """Record of a segment recall (zombie path)."""

    seg_id: str
    turn: int
    timestamp: float
    tokens: int
    recalled_from: str  # warm, cold, graveyard


@dataclass
class IngestEvent:
    """Record of a segment ingestion."""

    seg_id: str
    turn: int
    timestamp: float
    tokens: int
    role: str
    source: str | None


class MetricsCollector:
    """Collects and exports evaluation metrics.

    Designed to be attached to a ContextBus and record all events
    for post-hoc analysis in Jupyter notebooks.
    """

    def __init__(self) -> None:
        self.snapshots: list[TurnSnapshot] = []
        self.evictions: list[EvictionEvent] = []
        self.recalls: list[RecallEvent] = []
        self.ingestions: list[IngestEvent] = []
        self.agent_responses: list[dict[str, Any]] = []

        self._current_turn: int = 0

    def set_turn(self, turn: int) -> None:
        self._current_turn = turn

    def record_ingest(self, seg: Segment) -> None:
        self.ingestions.append(IngestEvent(
            seg_id=seg.seg_id,
            turn=self._current_turn,
            timestamp=time.time(),
            tokens=seg.token_count,
            role=seg.role.value,
            source=seg.source,
        ))

    def record_eviction_cycle(self, evicted: list[Segment], active_tokens: int) -> None:
        for seg in evicted:
            self.evictions.append(EvictionEvent(
                seg_id=seg.seg_id,
                turn=self._current_turn,
                timestamp=time.time(),
                tokens=seg.token_count,
                reason=seg.eviction_reason or "unknown",
                policy=seg.eviction_policy or "unknown",
                age_seconds=seg.age_seconds,
                idle_seconds=seg.idle_seconds,
                composite_score=seg.composite_score,
                source=seg.source,
            ))

    def record_recall(self, seg: Segment) -> None:
        self.recalls.append(RecallEvent(
            seg_id=seg.seg_id,
            turn=self._current_turn,
            timestamp=time.time(),
            tokens=seg.token_count,
            recalled_from=seg.tier.value,
        ))

    def record_agent_response(self, response_data: dict[str, Any]) -> None:
        response_data["turn"] = self._current_turn
        response_data["timestamp"] = time.time()
        self.agent_responses.append(response_data)

    def take_snapshot(self, bus_stats: dict) -> None:
        self.snapshots.append(TurnSnapshot(
            turn=self._current_turn,
            timestamp=time.time(),
            active_tokens=bus_stats["active_tokens"],
            active_segments=bus_stats["active_segments"],
            warm_count=bus_stats["store_stats"]["warm_count"],
            cold_count=bus_stats["store_stats"]["cold_count"],
            graveyard_count=bus_stats["store_stats"]["graveyard_count"],
            zombie_count=bus_stats["store_stats"]["zombie_count"],
            utilization=bus_stats["utilization"],
        ))

    # ── Export ───────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Return a summary of all collected metrics."""
        total_ingested = sum(e.tokens for e in self.ingestions)
        total_evicted = sum(e.tokens for e in self.evictions)
        total_recalled = sum(e.tokens for e in self.recalls)

        return {
            "total_turns": self._current_turn,
            "total_ingested_tokens": total_ingested,
            "total_evicted_tokens": total_evicted,
            "total_recalled_tokens": total_recalled,
            "eviction_count": len(self.evictions),
            "recall_count": len(self.recalls),
            "recall_rate": len(self.recalls) / len(self.evictions) if self.evictions else 0,
            "peak_utilization": max((s.utilization for s in self.snapshots), default=0),
            "avg_utilization": (
                sum(s.utilization for s in self.snapshots) / len(self.snapshots)
                if self.snapshots
                else 0
            ),
        }

    def export_json(self, path: Path) -> None:
        """Export all metrics to a JSON file for analysis."""
        data = {
            "summary": self.summary(),
            "snapshots": [s.__dict__ for s in self.snapshots],
            "evictions": [e.__dict__ for e in self.evictions],
            "recalls": [r.__dict__ for r in self.recalls],
            "ingestions": [i.__dict__ for i in self.ingestions],
            "agent_responses": self.agent_responses,
        }
        path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        logger.info("metrics_exported", path=str(path))
