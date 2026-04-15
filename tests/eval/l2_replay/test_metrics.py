"""Tests for L2 prompt-divergence replay metrics."""

from __future__ import annotations

from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.eval.l1_mechanism.runner import L1RunConfig, run_l1
from ctx_rm.eval.l2_replay.metrics import compute_replay_metrics
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode
from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind


def _seg(
    seg_id: str,
    turn: int,
    event: int,
    content: str,
    *,
    tokens: int = 100,
) -> TraceSegment:
    return TraceSegment(
        seg_id=seg_id,
        turn_index=turn,
        event_index=event,
        timestamp=float(event),
        kind=TraceSegmentKind.ASSISTANT_TEXT,
        content=content,
        token_count=tokens,
    )


def _trace() -> Trace:
    segs = [
        _seg("s0", 0, 0, "initial context", tokens=100),
        _seg("s1", 1, 1, "working set one", tokens=250),
        _seg("s2", 2, 2, "working set two", tokens=250),
        _seg("s3", 3, 3, "working set three", tokens=250),
    ]
    return Trace(trace_id="l2", source_path="mem", project="test", segments=segs)


def test_abundant_budget_matches_recorded_prefix() -> None:
    trace = _trace()
    graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
    result = run_l1(
        L1RunConfig(
            trace=trace,
            reference_graph=graph,
            policy_factory=lambda g: LRUPolicy(),
            policy_name="lru",
            token_budget=10_000,
        )
    )
    metrics = compute_replay_metrics(result, trace)

    assert metrics.mean_prompt_coverage == 1.0
    assert metrics.mean_prompt_jaccard == 1.0
    assert metrics.mean_token_savings == 0.0


def test_tight_budget_reduces_prompt_coverage_and_saves_tokens() -> None:
    trace = _trace()
    graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
    result = run_l1(
        L1RunConfig(
            trace=trace,
            reference_graph=graph,
            policy_factory=lambda g: LRUPolicy(),
            policy_name="lru",
            token_budget=300,
        )
    )
    metrics = compute_replay_metrics(result, trace)

    assert metrics.mean_prompt_coverage < 1.0
    assert metrics.mean_prompt_jaccard < 1.0
    assert metrics.mean_token_savings > 0.0

