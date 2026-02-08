"""Adaptive weights and policy knobs driven by feedback events."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ctx_rm.core.feedback import FeedbackTracker


_HIGH_RECALL_RATE = 0.3
_LOW_RECALL_RATE = 0.05
_MIN_EVENTS_FOR_SHIFT = 5

_CONSERVATIVE_BOOST = 0.15
_AGGRESSIVE_DECAY = 0.05

_DEFAULT_POLICY_PARAMS: dict[str, float] = {
    "headroom_ratio": 0.15,
    "eviction_aggressiveness": 1.0,
}


class AdaptiveWeights:
    """Maintains adaptation overlays for scorer and policy behavior."""

    def __init__(self) -> None:
        self.source_weights: dict[str, float] = {}
        self.importance_adjustments: dict[str, float] = {}
        self.policy_params: dict[str, float] = dict(_DEFAULT_POLICY_PARAMS)
        self._shift_count: int = 0

    @property
    def shift_count(self) -> int:
        return self._shift_count

    def source_multiplier(self, source: str | None) -> float:
        if source is None:
            return 1.0
        prefix = source.split(":")[0] if ":" in source else source
        return self.source_weights.get(prefix, 1.0)

    def importance_offset(self, seg_id: str) -> float:
        return self.importance_adjustments.get(seg_id, 0.0)

    def update_from_feedback(self, tracker: FeedbackTracker) -> None:
        """Apply one conservative/aggressive shift based on recent feedback."""
        if len(tracker.events_by_type("eviction")) < _MIN_EVENTS_FOR_SHIFT:
            return

        recall_rate = tracker.recall_rate()
        if recall_rate >= _HIGH_RECALL_RATE:
            self._apply_conservative_shift(tracker)
        elif recall_rate <= _LOW_RECALL_RATE:
            self._apply_aggressive_shift()

    def _apply_conservative_shift(self, tracker: FeedbackTracker) -> None:
        boosted_sources: set[str] = set()
        for event in tracker.events_by_type("recall"):
            source = event.get("source")
            if source is None:
                continue
            prefix = source.split(":")[0] if ":" in source else source
            if prefix in boosted_sources:
                continue
            current = self.source_weights.get(prefix, 1.0)
            self.source_weights[prefix] = min(2.0, current + _CONSERVATIVE_BOOST)
            boosted_sources.add(prefix)

        current_headroom = self.policy_params.get("headroom_ratio", 0.15)
        self.policy_params["headroom_ratio"] = min(0.35, current_headroom + 0.02)
        self._shift_count += 1

    def _apply_aggressive_shift(self) -> None:
        for prefix in list(self.source_weights):
            current = self.source_weights[prefix]
            if current > 1.0:
                self.source_weights[prefix] = max(1.0, current - _AGGRESSIVE_DECAY)
                if self.source_weights[prefix] == 1.0:
                    del self.source_weights[prefix]

        current_headroom = self.policy_params.get("headroom_ratio", 0.15)
        if current_headroom > 0.15:
            self.policy_params["headroom_ratio"] = max(0.15, current_headroom - 0.01)
        self._shift_count += 1

    def apply_to_composite(self, composite: float, source: str | None, seg_id: str) -> float:
        adjusted = composite * self.source_multiplier(source)
        adjusted += self.importance_offset(seg_id)
        return max(0.0, min(1.0, adjusted))

