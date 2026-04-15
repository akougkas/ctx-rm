"""L1 runner: deterministic trace replay through ContextBus.

Given a `Trace` and a policy factory, walks the trace's segments in event
order and calls `bus.ingest()` for each one. `ContextBus.ingest` handles
eviction internally when the budget is exceeded. At every turn boundary we
capture a `TurnSnapshot` of the active set, the bus token count, and the
segment IDs currently in active context. The metrics module consumes these
snapshots to produce per-trace aggregates.

The runner is the *only* place that bridges the eval layer (Trace,
ReferenceGraph, controls) and the runtime (ContextBus, Segment, Policy). All
the complexity of "how do we teach an eviction policy to understand our
oracle" is encapsulated here via `set_current_turn` hooks for the controls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.scorer import Scorer
from ctx_rm.core.segment import Segment, SegmentRole
from ctx_rm.eval.controls.oracle import OraclePolicy
from ctx_rm.eval.trace.reference_graph import ReferenceGraph
from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind

# Map eval-tier kinds to runtime SegmentRole values so the bus's role-based
# heuristics still fire correctly. The eval layer is strictly more granular
# than the runtime so this is a lossy many-to-one mapping — that's fine.
_KIND_TO_ROLE: dict[TraceSegmentKind, SegmentRole] = {
    TraceSegmentKind.SYSTEM: SegmentRole.SYSTEM,
    TraceSegmentKind.USER: SegmentRole.USER,
    TraceSegmentKind.ASSISTANT_TEXT: SegmentRole.ASSISTANT,
    TraceSegmentKind.ASSISTANT_THINKING: SegmentRole.ASSISTANT,
    TraceSegmentKind.TOOL_USE: SegmentRole.ASSISTANT,
    TraceSegmentKind.TOOL_RESULT: SegmentRole.TOOL,
    TraceSegmentKind.ATTACHMENT: SegmentRole.CONTEXT,
}

_KIND_TO_SOURCE: dict[TraceSegmentKind, str] = {
    TraceSegmentKind.SYSTEM: "system_prompt",
    TraceSegmentKind.USER: "user_task",
    TraceSegmentKind.ASSISTANT_TEXT: "assistant_response",
    TraceSegmentKind.ASSISTANT_THINKING: "assistant_thinking",
    TraceSegmentKind.TOOL_USE: "assistant_tool_call",
    TraceSegmentKind.TOOL_RESULT: "tool",
    TraceSegmentKind.ATTACHMENT: "attachment",
}


@dataclass
class TurnSnapshot:
    """State captured at each turn boundary during replay."""

    turn_index: int
    active_seg_ids: list[str]
    active_tokens: int
    evicted_cumulative: list[str]
    recalled_cumulative: list[str]


@dataclass
class L1RunConfig:
    """Inputs to one L1 run: one (trace, policy, budget) combination."""

    trace: Trace
    reference_graph: ReferenceGraph
    policy_factory: Callable[[ReferenceGraph], EvictionPolicy]
    policy_name: str
    token_budget: int
    headroom_ratio: float = 0.15
    scorer: Scorer | None = None
    # Pin system prompts so they never get evicted. Makes the run compatible
    # with the runtime AgentLoop which pins system segments by default.
    pin_system: bool = True


@dataclass
class L1Result:
    """Full replay result for one configuration.

    Metrics are deliberately left as raw material; `metrics.compute_metrics`
    turns this into a numeric summary. Keeping snapshots + eviction log
    means a single run can be post-processed multiple ways (for example,
    varying the "retention horizon" without re-running).
    """

    config: L1RunConfig
    snapshots: list[TurnSnapshot]
    evictions: list[tuple[str, int]] = field(default_factory=list)
    recalls: list[tuple[str, int]] = field(default_factory=list)
    ingested_count: int = 0
    final_active_tokens: int = 0
    final_store_stats: dict = field(default_factory=dict)


def _trace_to_segment(ts: TraceSegment, *, pin_system: bool) -> Segment:
    role = _KIND_TO_ROLE[ts.kind]
    source = _KIND_TO_SOURCE[ts.kind]
    return Segment(
        seg_id=ts.seg_id,
        content=ts.content,
        role=role,
        token_count=ts.token_count,
        source=source,
        pinned=(pin_system and ts.kind == TraceSegmentKind.SYSTEM),
        metadata={
            "kind": ts.kind.value,
            "tool_name": ts.tool_name,
            "tool_use_id": ts.tool_use_id,
            "source_file": ts.source_file,
        },
    )


def run_l1(config: L1RunConfig) -> L1Result:
    """Execute one L1 replay and return the raw result.

    The replay is a straight walk through the trace in `event_index` order.
    At each `turn_index` transition we emit a TurnSnapshot *before* the new
    turn's segments are ingested — the snapshot represents "what context
    the LLM would have seen at the start of turn N". A final snapshot is
    emitted after the last segment so end-of-trace metrics are available.
    """
    policy = config.policy_factory(config.reference_graph)
    store = TieredStore()
    evictions: list[tuple[str, int]] = []
    recalls: list[tuple[str, int]] = []

    def on_event(name: str, data: dict) -> None:
        seg_id = data.get("seg_id")
        if seg_id is None:
            return
        if name == "evict":
            evictions.append((seg_id, current_turn))
        elif name == "recall":
            recalls.append((seg_id, current_turn))

    bus = ContextBus(
        token_budget=config.token_budget,
        store=store,
        policy=policy,
        scorer=config.scorer,
        headroom_ratio=config.headroom_ratio,
        on_event=on_event,
    )

    snapshots: list[TurnSnapshot] = []
    current_turn = -1
    ingested = 0

    def _snapshot(turn: int) -> None:
        snapshots.append(
            TurnSnapshot(
                turn_index=turn,
                active_seg_ids=[s.seg_id for s in bus.active_segments],
                active_tokens=bus.active_tokens,
                evicted_cumulative=[sid for sid, _ in evictions],
                recalled_cumulative=[sid for sid, _ in recalls],
            )
        )

    for ts in config.trace.segments:
        # Skip empty-body segments to avoid noise in metrics.
        if not ts.content and ts.token_count == 0:
            continue

        if ts.turn_index != current_turn:
            if current_turn >= 0:
                _snapshot(current_turn)
            current_turn = ts.turn_index
            bus.advance_turn(turn_number=current_turn)
            if isinstance(policy, OraclePolicy):
                policy.set_current_turn(current_turn)

        seg = _trace_to_segment(ts, pin_system=config.pin_system)
        bus.ingest(seg)
        ingested += 1

    # Final snapshot at the very end.
    _snapshot(max(current_turn, 0))

    return L1Result(
        config=config,
        snapshots=snapshots,
        evictions=evictions,
        recalls=recalls,
        ingested_count=ingested,
        final_active_tokens=bus.active_tokens,
        final_store_stats=bus.get_stats()["store_stats"],
    )
