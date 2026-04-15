"""Frozen-trace L1 regression coverage for current baseline behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from ctx_rm.core.policies.arc import ARCPolicy
from ctx_rm.core.policies.innodb import InnoDBPolicy
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.eval.controls.oracle import OraclePolicy
from ctx_rm.eval.l1_mechanism.metrics import compute_metrics
from ctx_rm.eval.l1_mechanism.runner import L1RunConfig, run_l1
from ctx_rm.eval.trace.claude_code import load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode

EXPECTED_RETENTION_LRU = 1.0
# Locked baseline value. Any diff means the L1 runner or metric changed.
EXPECTED_RETENTION_ORACLE = 1.0
# Locked baseline value. Any diff means the L1 runner or metric changed.


def test_frozen_trace_l1_regression() -> None:
    path = Path("tests/eval/fixtures/frozen_trace.jsonl")
    trace = normalize(load_transcript(path), project="awoc")
    graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)

    lru_result = run_l1(
        L1RunConfig(
            trace=trace,
            reference_graph=graph,
            policy_factory=lambda g: LRUPolicy(),
            policy_name="lru",
            token_budget=8000,
            disable_bypass=True,
        )
    )
    oracle_result = run_l1(
        L1RunConfig(
            trace=trace,
            reference_graph=graph,
            policy_factory=lambda g: OraclePolicy(g),
            policy_name="oracle",
            token_budget=8000,
            disable_bypass=True,
        )
    )
    arc_result = run_l1(
        L1RunConfig(
            trace=trace,
            reference_graph=graph,
            policy_factory=lambda g: ARCPolicy(capacity_tokens=8000),
            policy_name="arc",
            token_budget=8000,
            disable_bypass=True,
        )
    )
    innodb_result = run_l1(
        L1RunConfig(
            trace=trace,
            reference_graph=graph,
            policy_factory=lambda g: InnoDBPolicy(capacity_tokens=8000),
            policy_name="innodb",
            token_budget=8000,
            disable_bypass=True,
        )
    )

    lru_metrics = compute_metrics(lru_result, trace, graph)
    oracle_metrics = compute_metrics(oracle_result, trace, graph)

    assert lru_metrics.critical_segment_retention == pytest.approx(
        EXPECTED_RETENTION_LRU,
        abs=1e-6,
    )
    assert oracle_metrics.critical_segment_retention == pytest.approx(
        EXPECTED_RETENTION_ORACLE,
        abs=1e-6,
    )

    lru_evictions = [sid for sid, _ in lru_result.evictions]
    arc_evictions = [sid for sid, _ in arc_result.evictions]
    innodb_evictions = [sid for sid, _ in innodb_result.evictions]
    assert lru_evictions == arc_evictions == innodb_evictions
