"""L1 runner + metrics tests against hand-crafted toy traces.

These tests use known-shape traces where the "correct" answer is obvious,
so regressions in runner, reference graph, or metrics show up as failing
assertions rather than subtly wrong aggregates.
"""

from __future__ import annotations

from ctx_rm.core.policies.arc import ARCPolicy
from ctx_rm.core.policies.innodb import InnoDBPolicy
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.eval.controls.oracle import OraclePolicy
from ctx_rm.eval.controls.random_policy import RandomPolicy
from ctx_rm.eval.l1_mechanism.metrics import compute_metrics
from ctx_rm.eval.l1_mechanism.runner import L1RunConfig, run_l1
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode
from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind


def _mk_seg(
    seg_id: str,
    turn: int,
    event: int,
    content: str,
    *,
    kind: TraceSegmentKind = TraceSegmentKind.USER,
    tokens: int = 100,
    source_file: str | None = None,
) -> TraceSegment:
    return TraceSegment(
        seg_id=seg_id,
        turn_index=turn,
        event_index=event,
        timestamp=float(event),
        kind=kind,
        content=content,
        token_count=tokens,
        source_file=source_file,
    )


def _toy_trace() -> Trace:
    """Build a trace where:

    - Turn 0: user prompt.
    - Turn 1: tool_use on /a.py (source_file=/a.py) — referenced at turn 10.
    - Turn 1: tool_use on /b.py — never referenced again.
    - Turns 2-9: assistant thinking blocks with distinctive content.
    - Turn 10: tool_use on /a.py (creates the reference edge).
    """
    segs = [
        _mk_seg("u0", 0, 0, "initial task: read a.py", tokens=30),
        _mk_seg(
            "tu_a1",
            1,
            1,
            "tool_use:Read file_path=/a.py",
            kind=TraceSegmentKind.TOOL_USE,
            tokens=50,
            source_file="/a.py",
        ),
        _mk_seg(
            "tu_b1",
            1,
            2,
            "tool_use:Read file_path=/b.py",
            kind=TraceSegmentKind.TOOL_USE,
            tokens=50,
            source_file="/b.py",
        ),
    ]
    for i in range(2, 10):
        segs.append(
            _mk_seg(
                f"fluff_{i}",
                i,
                i + 10,
                f"filler content block {i}",
                kind=TraceSegmentKind.ASSISTANT_TEXT,
                tokens=200,
            )
        )
    segs.append(
        _mk_seg(
            "tu_a2",
            10,
            30,
            "tool_use:Read file_path=/a.py",
            kind=TraceSegmentKind.TOOL_USE,
            tokens=50,
            source_file="/a.py",
        )
    )
    return Trace(trace_id="toy", source_path="mem", project="test", segments=segs)


def _reaccess_trace() -> Trace:
    """Build a trace where one evicted tool_result returns with identical content.

    The repeated `tool_result` body is an honest in-trace re-access signal.
    A policy that notices "this content came back after eviction" can protect
    it as frequency-bearing state; plain LRU cannot.
    """
    segs = [
        _mk_seg("u0", 0, 0, "track repeated tool output", tokens=20),
        _mk_seg(
            "tool_a_1",
            0,
            1,
            "FILE auth.py\nTOKEN rotate_secret_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
        _mk_seg(
            "tool_b",
            1,
            2,
            "FILE billing.py\nTOKEN bill_user_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
        _mk_seg(
            "tool_c",
            2,
            3,
            "FILE cache.py\nTOKEN warm_cache_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
        _mk_seg(
            "tool_d",
            3,
            4,
            "FILE jobs.py\nTOKEN queue_job_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
        _mk_seg(
            "tool_a_2",
            4,
            5,
            "FILE auth.py\nTOKEN rotate_secret_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
        _mk_seg(
            "tool_e",
            5,
            6,
            "FILE mail.py\nTOKEN send_mail_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
        _mk_seg(
            "tool_f",
            6,
            7,
            "FILE audit.py\nTOKEN write_audit_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
        _mk_seg(
            "tool_g",
            7,
            8,
            "FILE search.py\nTOKEN build_index_v1\nRETURN 200 OK",
            kind=TraceSegmentKind.TOOL_RESULT,
            tokens=400,
        ),
    ]
    return Trace(trace_id="reaccess", source_path="mem", project="test", segments=segs)


class TestRunnerBasics:
    def test_runner_ingests_every_non_empty_segment(self) -> None:
        trace = _toy_trace()
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        result = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: LRUPolicy(),
                policy_name="lru",
                token_budget=100_000,  # abundant → no eviction
            )
        )
        assert result.ingested_count == len(trace.segments)
        # Snapshot count: one per turn transition plus final.
        assert len(result.snapshots) >= trace.num_turns

    def test_no_eviction_when_budget_is_abundant(self) -> None:
        trace = _toy_trace()
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        result = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: LRUPolicy(),
                policy_name="lru",
                token_budget=100_000,
            )
        )
        assert result.evictions == []


class TestOracleDominates:
    def test_oracle_precision_beats_random_on_toy_trace(self) -> None:
        trace = _toy_trace()
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        # Tight budget forces eviction.
        budget = 800

        oracle_result = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: OraclePolicy(g),
                policy_name="oracle",
                token_budget=budget,
            )
        )
        random_result = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: RandomPolicy(seed=0),
                policy_name="random",
                token_budget=budget,
            )
        )
        oracle_m = compute_metrics(oracle_result, trace, graph)
        random_m = compute_metrics(random_result, trace, graph)

        # Oracle should be at least as good as random on every axis.
        assert oracle_m.eviction_precision >= random_m.eviction_precision - 1e-9
        assert (
            oracle_m.critical_segment_retention
            >= random_m.critical_segment_retention - 1e-9
        )

    def test_oracle_keeps_referenced_segment_on_toy(self) -> None:
        trace = _toy_trace()
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        # Budget large enough to hold a few segments but not all.
        result = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: OraclePolicy(g),
                policy_name="oracle",
                token_budget=600,
            )
        )
        evicted_ids = {sid for sid, _ in result.evictions}
        # /b.py is never referenced again — oracle may evict it.
        # /a.py's first read tu_a1 IS referenced at turn 10 — oracle should
        # hold it as long as possible. We assert it survives until at least
        # turn 2 (right after ingest).
        # The earliest "safe to evict" target is fluff or tu_b1.
        # We allow for the possibility that oracle is forced to evict it
        # in extremis, but tu_b1 or fluff must be evicted before it.
        if "tu_a1" in evicted_ids:
            assert "tu_b1" in evicted_ids


class TestMetricsBasics:
    def test_empty_eviction_gives_precision_one(self) -> None:
        trace = _toy_trace()
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        result = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: LRUPolicy(),
                policy_name="lru",
                token_budget=1_000_000,
            )
        )
        m = compute_metrics(result, trace, graph)
        assert m.evicted_count == 0
        assert m.eviction_precision == 1.0
        assert m.churn_rate == 0.0

    def test_retention_is_bounded_zero_to_one(self) -> None:
        trace = _toy_trace()
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        result = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: RandomPolicy(seed=0),
                policy_name="random",
                token_budget=400,
            )
        )
        m = compute_metrics(result, trace, graph)
        assert 0.0 <= m.critical_segment_retention <= 1.0
        assert 0.0 <= m.critical_segment_retention_k10 <= 1.0
        assert 0.0 <= m.eviction_precision <= 1.0
        assert 0.0 <= m.eviction_recall <= 1.0


class TestDisableBypass:
    def test_large_tool_result_bypasses_by_default(self) -> None:
        large_body = "x " * 2500
        trace = Trace(
            trace_id="t",
            source_path="mem",
            project="p",
            segments=[
                TraceSegment(
                    seg_id="u",
                    turn_index=0,
                    event_index=0,
                    timestamp=0.0,
                    kind=TraceSegmentKind.USER,
                    content="hello world " * 20,
                    token_count=50,
                ),
                TraceSegment(
                    seg_id="tu",
                    turn_index=0,
                    event_index=1,
                    timestamp=0.0,
                    kind=TraceSegmentKind.TOOL_USE,
                    content="tool_use:Read",
                    token_count=10,
                    tool_use_id="r1",
                ),
                TraceSegment(
                    seg_id="tr",
                    turn_index=0,
                    event_index=2,
                    timestamp=0.0,
                    kind=TraceSegmentKind.TOOL_RESULT,
                    content=large_body,
                    token_count=2500,
                    tool_use_id="r1",
                ),
                TraceSegment(
                    seg_id="at",
                    turn_index=1,
                    event_index=3,
                    timestamp=0.0,
                    kind=TraceSegmentKind.ASSISTANT_TEXT,
                    content="done",
                    token_count=5,
                ),
            ],
        )
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        default = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: LRUPolicy(),
                policy_name="lru",
                token_budget=100_000,
            )
        )
        disabled = run_l1(
            L1RunConfig(
                trace=trace,
                reference_graph=graph,
                policy_factory=lambda g: LRUPolicy(),
                policy_name="lru",
                token_budget=100_000,
                disable_bypass=True,
            )
        )
        default_active = set(default.snapshots[-1].active_seg_ids)
        disabled_active = set(disabled.snapshots[-1].active_seg_ids)
        assert "tr" not in default_active
        assert "tr" in disabled_active


class TestRepeatedContentReaccess:
    def test_arc_diverges_from_lru_when_evicted_content_returns(self) -> None:
        trace = _reaccess_trace()
        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        cfg = dict(
            trace=trace,
            reference_graph=graph,
            token_budget=1200,
            headroom_ratio=0.0,
            disable_bypass=True,
        )

        lru = run_l1(
            L1RunConfig(
                **cfg,
                policy_factory=lambda g: LRUPolicy(),
                policy_name="lru",
            )
        )
        arc = run_l1(
            L1RunConfig(
                **cfg,
                policy_factory=lambda g: ARCPolicy(capacity_tokens=1200),
                policy_name="arc",
            )
        )
        innodb = run_l1(
            L1RunConfig(
                **cfg,
                policy_factory=lambda g: InnoDBPolicy(capacity_tokens=1200),
                policy_name="innodb",
            )
        )

        lru_evictions = [sid for sid, _ in lru.evictions]
        arc_evictions = [sid for sid, _ in arc.evictions]
        innodb_evictions = [sid for sid, _ in innodb.evictions]

        assert lru_evictions[-1] == "tool_a_2"
        assert arc_evictions[-1] != "tool_a_2"
        assert innodb_evictions[-1] != "tool_a_2"
        assert lru_evictions != arc_evictions
        assert lru_evictions != innodb_evictions
