"""L1 metrics: pure-function reducers over L1Result.

Every metric is a function of (trace, reference_graph, result). No stateful
aggregation, no hidden dependencies — you can recompute any metric from the
stored result, which is what makes the L1 tier hermetic and debuggable.

Metric definitions (paper reports these verbatim):

- **eviction_precision** = |evicted ∩ unreferenced| / |evicted|
  Of segments we threw away, what fraction were safe to throw away
  (never referenced again in the rest of the trace)?

- **eviction_recall** = |evicted ∩ unreferenced| / |unreferenced_ever_active|
  Of the segments that were safe to throw away and that we actually had in
  active context at some point, how many did we actually evict? Uses the
  "ever active" denominator so pinned / never-active segments don't inflate
  the ratio.

- **critical_segment_retention(k)** = mean over turns of
    |{s in snapshot : reference_graph says s is referenced within [t+1, t+k]}|
    / |{s that WILL be referenced within [t+1, t+k]}|
  "At each turn, what fraction of segments the LLM will need in the next k
  turns are still in active context right now?" This is the headline number.

- **churn_rate** = |{s : s was evicted and later recalled}| / |evicted|
  Fraction of evictions that thrashed.

- **tokens_evicted / tokens_recalled / peak_active_tokens** - cost proxies.
"""

from __future__ import annotations

from dataclasses import dataclass

from ctx_rm.eval.l1_mechanism.runner import L1Result
from ctx_rm.eval.trace.reference_graph import ReferenceGraph
from ctx_rm.eval.trace.schema import Trace, TraceSegment


@dataclass
class L1Metrics:
    """Per-run L1 metric bundle, ready for aggregation and reporting."""

    trace_id: str
    policy_name: str
    token_budget: int
    ingested_count: int
    evicted_count: int
    recalled_count: int
    unreferenced_ever_active: int
    peak_active_tokens: int
    final_active_tokens: int

    eviction_precision: float
    eviction_recall: float
    churn_rate: float

    # Retention is parameterized by horizon k (turns). We store a single
    # default value (k=5) and let the runner compute additional horizons if
    # desired. k=5 approximates "the next few LLM calls".
    critical_segment_retention_k5: float

    # Aggregate cost proxies.
    tokens_evicted: int
    tokens_recalled: int

    def as_row(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "policy": self.policy_name,
            "budget": self.token_budget,
            "n_ingested": self.ingested_count,
            "n_evicted": self.evicted_count,
            "n_recalled": self.recalled_count,
            "unreferenced_ever_active": self.unreferenced_ever_active,
            "peak_active_tokens": self.peak_active_tokens,
            "final_active_tokens": self.final_active_tokens,
            "eviction_precision": self.eviction_precision,
            "eviction_recall": self.eviction_recall,
            "churn_rate": self.churn_rate,
            "retention@5": self.critical_segment_retention_k5,
            "tokens_evicted": self.tokens_evicted,
            "tokens_recalled": self.tokens_recalled,
        }


def compute_metrics(
    result: L1Result,
    trace: Trace,
    graph: ReferenceGraph,
    *,
    retention_horizon: int = 5,
) -> L1Metrics:
    """Reduce one L1Result plus its trace+graph into an L1Metrics bundle."""
    seg_by_id: dict[str, TraceSegment] = {s.seg_id: s for s in trace.segments}
    referenced_set = graph.referenced_seg_ids()

    # Set of segments that ever appeared in active context. Derived from
    # snapshots so "segments that were admitted straight to Warm" don't
    # count. This keeps the recall denominator honest.
    ever_active: set[str] = set()
    for snap in result.snapshots:
        ever_active.update(snap.active_seg_ids)
    # Also include segments that were evicted (they were active just before
    # being evicted — the snapshot taken *after* eviction may miss them).
    for sid, _ in result.evictions:
        ever_active.add(sid)

    # Eviction precision / recall — computed against the "ever active"
    # denominator so pinned and admission-bypassed segments don't skew the
    # ratio. "Unreferenced" here means "not referenced again at any future
    # turn", i.e. absent from graph.referenced_seg_ids().
    evicted_set = {sid for sid, _ in result.evictions}
    evicted_unreferenced = len(evicted_set - referenced_set)
    evicted_total = len(evicted_set)
    eviction_precision = evicted_unreferenced / evicted_total if evicted_total else 1.0

    ever_active_unreferenced = ever_active - referenced_set
    denom_recall = len(ever_active_unreferenced)
    eviction_recall = evicted_unreferenced / denom_recall if denom_recall else 1.0

    # Churn: evictions whose seg_id was later recalled. Uses the bus's
    # recall stream, which fires on TieredStore.recall hits.
    recalled_set = {sid for sid, _ in result.recalls}
    churned = evicted_set & recalled_set
    churn_rate = len(churned) / evicted_total if evicted_total else 0.0

    # Token cost proxies.
    def _tokens_for(ids: set[str] | list[str]) -> int:
        return sum(seg_by_id[sid].token_count for sid in ids if sid in seg_by_id)

    tokens_evicted = _tokens_for(evicted_set)
    tokens_recalled = _tokens_for(recalled_set)
    peak = max((snap.active_tokens for snap in result.snapshots), default=0)

    # Critical-segment retention@k. For each turn snapshot, find segments
    # that are referenced within [t+1, t+k], compute the fraction still in
    # active context. Average across turns weighted uniformly.
    retention = _critical_segment_retention(result, trace, graph, horizon=retention_horizon)

    return L1Metrics(
        trace_id=trace.trace_id,
        policy_name=result.config.policy_name,
        token_budget=result.config.token_budget,
        ingested_count=result.ingested_count,
        evicted_count=evicted_total,
        recalled_count=len(recalled_set),
        unreferenced_ever_active=denom_recall,
        peak_active_tokens=peak,
        final_active_tokens=result.final_active_tokens,
        eviction_precision=eviction_precision,
        eviction_recall=eviction_recall,
        churn_rate=churn_rate,
        critical_segment_retention_k5=retention,
        tokens_evicted=tokens_evicted,
        tokens_recalled=tokens_recalled,
    )


def _critical_segment_retention(
    result: L1Result,
    trace: Trace,
    graph: ReferenceGraph,
    *,
    horizon: int,
) -> float:
    """Mean fraction of "referenced within next k turns" segments still live.

    For each snapshot at turn t, the set of "critical" segments is every
    earlier-or-current segment whose earliest future reference lies in
    [t+1, t+horizon]. The retention is that set ∩ active / that set. We
    average across snapshots; a snapshot with an empty critical set
    contributes 1.0 (trivially retaining nothing is perfect retention).
    """
    # Precompute which segments exist as of each turn t so we don't give
    # credit for "retaining" segments that haven't been ingested yet.
    segs_in_order = sorted(trace.segments, key=lambda s: s.event_index)
    seg_turns: dict[str, int] = {s.seg_id: s.turn_index for s in segs_in_order}

    per_turn_scores: list[float] = []
    for snap in result.snapshots:
        t = snap.turn_index
        active_set = set(snap.active_seg_ids)

        critical_ids: set[str] = set()
        for sid, seg_turn in seg_turns.items():
            if seg_turn > t:
                continue
            next_ref = graph.earliest_future_turn(sid)
            if next_ref is None:
                continue
            if t < next_ref <= t + horizon:
                critical_ids.add(sid)

        if not critical_ids:
            per_turn_scores.append(1.0)
            continue
        retained = len(critical_ids & active_set)
        per_turn_scores.append(retained / len(critical_ids))

    if not per_turn_scores:
        return 1.0
    return sum(per_turn_scores) / len(per_turn_scores)
