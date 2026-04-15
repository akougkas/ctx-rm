"""Tests for OraclePolicy and RandomPolicy."""

from __future__ import annotations

from ctx_rm.core.segment import Segment, SegmentRole
from ctx_rm.eval.controls.oracle import OraclePolicy
from ctx_rm.eval.controls.random_policy import RandomPolicy
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode
from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind


def _seg(seg_id: str, tokens: int = 100) -> Segment:
    return Segment(
        seg_id=seg_id,
        content=f"content for {seg_id}",
        role=SegmentRole.USER,
        token_count=tokens,
        source="user_task",
    )


def _trace_seg(
    seg_id: str,
    turn: int,
    event: int,
    *,
    kind: TraceSegmentKind = TraceSegmentKind.TOOL_USE,
    content: str = "x",
    source_file: str | None = None,
) -> TraceSegment:
    return TraceSegment(
        seg_id=seg_id,
        turn_index=turn,
        event_index=event,
        timestamp=float(event),
        kind=kind,
        content=content,
        token_count=10,
        source_file=source_file,
    )


class TestOraclePolicy:
    def test_evicts_unreferenced_before_referenced(self) -> None:
        # Build a graph where "needed" is referenced at turn 5 and "safe" is not.
        trace = Trace(
            trace_id="t",
            source_path="mem",
            project="test",
            segments=[
                _trace_seg(
                    "needed",
                    0,
                    0,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read file_path=/a.py",
                    source_file="/a.py",
                ),
                _trace_seg(
                    "safe",
                    0,
                    1,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read file_path=/b.py",
                    source_file="/b.py",
                ),
                # Future reference only to /a.py
                _trace_seg(
                    "ref",
                    5,
                    2,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read file_path=/a.py",
                    source_file="/a.py",
                ),
            ],
        )
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        policy = OraclePolicy(graph)
        policy.set_current_turn(1)

        candidates = [_seg("needed"), _seg("safe")]
        evicted = policy.select_evictions(candidates, tokens_to_free=50)
        assert len(evicted) == 1
        assert evicted[0].seg_id == "safe"

    def test_evicts_referenced_if_forced(self) -> None:
        # Only referenced segments available; oracle must still evict one.
        trace = Trace(
            trace_id="t",
            source_path="mem",
            project="test",
            segments=[
                _trace_seg(
                    "a",
                    0,
                    0,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read file_path=/a.py",
                    source_file="/a.py",
                ),
                _trace_seg(
                    "b",
                    0,
                    1,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read file_path=/b.py",
                    source_file="/b.py",
                ),
                _trace_seg(
                    "ref_a_soon",
                    2,
                    2,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read file_path=/a.py",
                    source_file="/a.py",
                ),
                _trace_seg(
                    "ref_b_later",
                    20,
                    3,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read file_path=/b.py",
                    source_file="/b.py",
                ),
            ],
        )
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        policy = OraclePolicy(graph)
        policy.set_current_turn(1)

        # Both a and b are referenced in the future — a at turn 2, b at turn 20.
        # Oracle should prefer to evict b (furthest future reference).
        evicted = policy.select_evictions([_seg("a"), _seg("b")], tokens_to_free=50)
        assert len(evicted) == 1
        assert evicted[0].seg_id == "b"


class TestRandomPolicy:
    def test_is_deterministic_with_seed(self) -> None:
        cands_a = [_seg(f"s{i}") for i in range(10)]
        cands_b = [_seg(f"s{i}") for i in range(10)]
        p1 = RandomPolicy(seed=42)
        p2 = RandomPolicy(seed=42)
        e1 = p1.select_evictions(cands_a, tokens_to_free=300)
        e2 = p2.select_evictions(cands_b, tokens_to_free=300)
        assert [s.seg_id for s in e1] == [s.seg_id for s in e2]

    def test_different_seeds_differ(self) -> None:
        cands_a = [_seg(f"s{i}") for i in range(20)]
        cands_b = [_seg(f"s{i}") for i in range(20)]
        e1 = RandomPolicy(seed=1).select_evictions(cands_a, tokens_to_free=500)
        e2 = RandomPolicy(seed=2).select_evictions(cands_b, tokens_to_free=500)
        assert [s.seg_id for s in e1] != [s.seg_id for s in e2]
