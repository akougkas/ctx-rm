"""L2 replay metrics: prompt-shape divergence against the recorded prefix.

L1 asks whether the policy kept future-critical segments alive. L2 keeps the
same replay engine but changes the lens: at each turn boundary, how far does
the ctx-rm-rendered active set diverge from the full recorded prefix the agent
originally had available?
"""

from __future__ import annotations

from dataclasses import dataclass

from ctx_rm.eval.l1_mechanism.runner import L1Result
from ctx_rm.eval.trace.schema import Trace


@dataclass
class L2Metrics:
    """Per-run L2 metric bundle, ready for aggregation and reporting."""

    trace_id: str
    policy_name: str
    token_budget: int
    turn_count: int
    mean_prompt_coverage: float
    mean_prompt_jaccard: float
    mean_token_savings: float
    mean_active_tokens: float
    mean_recorded_tokens: float

    def as_row(self) -> dict[str, float | int | str]:
        return {
            "trace_id": self.trace_id,
            "policy": self.policy_name,
            "budget": self.token_budget,
            "turns": self.turn_count,
            "prompt_coverage": self.mean_prompt_coverage,
            "prompt_jaccard": self.mean_prompt_jaccard,
            "token_savings": self.mean_token_savings,
            "active_tokens": self.mean_active_tokens,
            "recorded_tokens": self.mean_recorded_tokens,
        }


def compute_replay_metrics(result: L1Result, trace: Trace) -> L2Metrics:
    """Reduce an L1 replay result into L2 prompt-divergence metrics."""
    segs_in_order = sorted(trace.segments, key=lambda s: s.event_index)
    segs_by_turn: dict[int, list] = {}
    for seg in segs_in_order:
        if not seg.content and seg.token_count == 0:
            continue
        segs_by_turn.setdefault(seg.turn_index, []).append(seg)

    prefix_seg_ids: set[str] = set()
    prefix_tokens = 0
    next_turn_to_fold = 0

    coverage_scores: list[float] = []
    jaccard_scores: list[float] = []
    savings_scores: list[float] = []
    active_token_scores: list[int] = []
    recorded_token_scores: list[int] = []

    for snap in result.snapshots:
        while next_turn_to_fold <= snap.turn_index:
            for seg in segs_by_turn.get(next_turn_to_fold, []):
                prefix_seg_ids.add(seg.seg_id)
                prefix_tokens += seg.token_count
            next_turn_to_fold += 1

        active_set = set(snap.active_seg_ids)
        overlap = len(prefix_seg_ids & active_set)
        coverage_scores.append(overlap / len(prefix_seg_ids) if prefix_seg_ids else 1.0)

        union = len(prefix_seg_ids | active_set)
        jaccard_scores.append(overlap / union if union else 1.0)

        if prefix_tokens:
            savings_scores.append(1.0 - (snap.active_tokens / prefix_tokens))
        else:
            savings_scores.append(0.0)
        active_token_scores.append(snap.active_tokens)
        recorded_token_scores.append(prefix_tokens)

    n = len(result.snapshots)
    if n == 0:
        return L2Metrics(
            trace_id=trace.trace_id,
            policy_name=result.config.policy_name,
            token_budget=result.config.token_budget,
            turn_count=0,
            mean_prompt_coverage=1.0,
            mean_prompt_jaccard=1.0,
            mean_token_savings=0.0,
            mean_active_tokens=0.0,
            mean_recorded_tokens=0.0,
        )

    return L2Metrics(
        trace_id=trace.trace_id,
        policy_name=result.config.policy_name,
        token_budget=result.config.token_budget,
        turn_count=n,
        mean_prompt_coverage=sum(coverage_scores) / n,
        mean_prompt_jaccard=sum(jaccard_scores) / n,
        mean_token_savings=sum(savings_scores) / n,
        mean_active_tokens=sum(active_token_scores) / n,
        mean_recorded_tokens=sum(recorded_token_scores) / n,
    )

