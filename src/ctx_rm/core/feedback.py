"""Feedback tracking for adaptation loops.

Tracks eviction/recall/evaluation outcomes in a bounded event log so adaptive
components can adjust retention behavior over long sessions.
"""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ctx_rm.core.segment import Segment


class FeedbackTracker:
    """Records events used by adaptive scoring and policy controls."""

    def __init__(self, max_events: int = 2048) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)

    @property
    def events(self) -> list[dict[str, Any]]:
        """Snapshot of recorded events (oldest first)."""
        return list(self._events)

    @property
    def event_count(self) -> int:
        return len(self._events)

    def on_eviction(self, segment: Segment) -> None:
        self._events.append({
            "type": "eviction",
            "seg_id": segment.seg_id,
            "source": segment.source,
            "composite_score": segment.composite_score,
            "token_count": segment.token_count,
            "ts": time.time(),
        })

    def on_recall(self, segment: Segment) -> None:
        self._events.append({
            "type": "recall",
            "seg_id": segment.seg_id,
            "source": segment.source,
            "composite_score": segment.composite_score,
            "token_count": segment.token_count,
            "ts": time.time(),
        })

    def on_re_eviction(self, segment: Segment) -> None:
        self._events.append({
            "type": "re_eviction",
            "seg_id": segment.seg_id,
            "source": segment.source,
            "composite_score": segment.composite_score,
            "token_count": segment.token_count,
            "ts": time.time(),
        })

    def on_eval_result(self, check: str, passed: bool) -> None:
        self._events.append({
            "type": "eval",
            "check": check,
            "passed": passed,
            "ts": time.time(),
        })

    def events_by_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self._events if e["type"] == event_type]

    def recall_rate(self) -> float:
        """Fraction of evictions that later required recall."""
        evictions = sum(1 for e in self._events if e["type"] == "eviction")
        if evictions == 0:
            return 0.0
        recalls = sum(1 for e in self._events if e["type"] == "recall")
        return min(1.0, recalls / evictions)

    def eval_pass_rate(self) -> float:
        """Fraction of eval checks that passed (1.0 when no checks seen)."""
        eval_events = [e for e in self._events if e["type"] == "eval"]
        if not eval_events:
            return 1.0
        passed = sum(1 for e in eval_events if e["passed"])
        return passed / len(eval_events)

