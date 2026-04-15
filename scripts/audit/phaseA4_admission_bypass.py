"""Phase A4: quantify admission-bypass impact on real traces.

ContextBus._should_bypass_active routes segments whose `source` starts with
'file_read' or 'tool' AND whose token_count > admission_threshold (default
2000) directly to Warm, never entering Active context. In the L1 runner the
only trace kind that maps to source='tool' is TOOL_RESULT (see
runner._KIND_TO_SOURCE), so bypass fires exactly on TOOL_RESULT segments
whose token_count > threshold.

This script quantifies, on a filtered corpus:

1. What fraction of segments / tokens admission bypass swallows at each of
   several thresholds {500, 1000, 2000, 4000, 8000}.
2. Among bypassed segments, what fraction are "important" by the strict
   reference graph (have outgoing edges -- later segments reference them).
3. Per-trace histogram so we can spot traces where bypass dominates.

A bypass that removes mostly unreferenced content is a free lunch.
A bypass that removes heavily referenced content is a confound: the L1
metrics will credit the policy for retaining what the *bus* kept away
from eviction, not what the *policy* chose.

Usage::

    python scripts/audit/phaseA4_admission_bypass.py \\
        --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \\
        --project awoc \\
        --min-segments 40 --min-turns 8 --min-tool-use 8 --min-rereads 1 \\
        --max-traces 200 \\
        --out docs/eval/phaseA4_bypass_awoc.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript  # noqa: E402
from ctx_rm.eval.trace.normalize import normalize  # noqa: E402
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode  # noqa: E402
from ctx_rm.eval.trace.schema import TraceSegmentKind  # noqa: E402

_BYPASS_KINDS = frozenset({TraceSegmentKind.TOOL_RESULT})
_THRESHOLDS = (500, 1000, 2000, 4000, 8000)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-dir", type=Path, required=True)
    ap.add_argument("--project", type=str, required=True)
    ap.add_argument("--min-segments", type=int, default=40)
    ap.add_argument("--min-turns", type=int, default=8)
    ap.add_argument("--min-tool-use", type=int, default=8)
    ap.add_argument("--min-rereads", type=int, default=1)
    ap.add_argument("--max-traces", type=int, default=200)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    paths = discover_transcripts(args.trace_dir)
    loaded = 0
    per_trace: list[dict] = []

    for path in paths:
        if loaded >= args.max_traces:
            break
        try:
            lt = load_transcript(path)
            trace = normalize(lt, project=args.project)
        except Exception:
            continue
        if len(trace.segments) < args.min_segments:
            continue
        if trace.num_turns < args.min_turns:
            continue
        tool_uses = sum(1 for s in trace.segments if s.kind == TraceSegmentKind.TOOL_USE)
        if tool_uses < args.min_tool_use:
            continue
        seen_paths: set[str] = set()
        rereads = 0
        for s in trace.segments:
            if s.kind == TraceSegmentKind.TOOL_USE and s.source_file:
                if s.source_file in seen_paths:
                    rereads += 1
                else:
                    seen_paths.add(s.source_file)
        if rereads < args.min_rereads:
            continue

        graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
        referenced = graph.referenced_seg_ids()

        total_segs = len(trace.segments)
        total_tok = trace.total_tokens

        per_threshold: dict[int, dict] = {}
        for thr in _THRESHOLDS:
            bypassed = [
                s
                for s in trace.segments
                if s.kind in _BYPASS_KINDS and s.token_count > thr
            ]
            by_ref = [s for s in bypassed if s.seg_id in referenced]
            per_threshold[thr] = {
                "bypassed_segments": len(bypassed),
                "bypassed_tokens": sum(s.token_count for s in bypassed),
                "bypassed_and_referenced_segments": len(by_ref),
                "bypassed_and_referenced_tokens": sum(s.token_count for s in by_ref),
            }

        per_trace.append(
            {
                "trace_id": trace.trace_id,
                "path": str(path),
                "segments": total_segs,
                "turns": trace.num_turns,
                "tokens": total_tok,
                "tool_result_count": sum(
                    1 for s in trace.segments if s.kind == TraceSegmentKind.TOOL_RESULT
                ),
                "tool_result_tokens": sum(
                    s.token_count
                    for s in trace.segments
                    if s.kind == TraceSegmentKind.TOOL_RESULT
                ),
                "referenced_segs": len(referenced),
                "bypass_by_threshold": per_threshold,
            }
        )
        loaded += 1

    # Aggregate.
    agg: dict[int, dict] = {}
    for thr in _THRESHOLDS:
        segs = [t["bypass_by_threshold"][thr]["bypassed_segments"] for t in per_trace]
        toks = [t["bypass_by_threshold"][thr]["bypassed_tokens"] for t in per_trace]
        ref_segs = [
            t["bypass_by_threshold"][thr]["bypassed_and_referenced_segments"] for t in per_trace
        ]
        ref_toks = [
            t["bypass_by_threshold"][thr]["bypassed_and_referenced_tokens"] for t in per_trace
        ]
        total_segs_sum = sum(t["segments"] for t in per_trace)
        total_tok_sum = sum(t["tokens"] for t in per_trace)
        agg[thr] = {
            "sum_bypassed_segments": sum(segs),
            "sum_bypassed_tokens": sum(toks),
            "sum_bypassed_and_referenced_segments": sum(ref_segs),
            "sum_bypassed_and_referenced_tokens": sum(ref_toks),
            "total_segments": total_segs_sum,
            "total_tokens": total_tok_sum,
            "frac_segs_bypassed": (sum(segs) / total_segs_sum) if total_segs_sum else 0.0,
            "frac_tokens_bypassed": (sum(toks) / total_tok_sum) if total_tok_sum else 0.0,
            "frac_bypassed_are_referenced": (
                sum(ref_segs) / sum(segs) if sum(segs) else 0.0
            ),
            "frac_bypassed_tokens_are_referenced": (
                sum(ref_toks) / sum(toks) if sum(toks) else 0.0
            ),
        }

    out = {
        "corpus": str(args.trace_dir),
        "project": args.project,
        "n_traces": len(per_trace),
        "aggregate_by_threshold": agg,
        "per_trace": per_trace,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        json.dump(out, fh, indent=2)

    print(f"traces: {len(per_trace)}")
    print(
        f"{'threshold':>9}  {'bypass_segs%':>12}  {'bypass_tok%':>12}  "
        f"{'ref_segs%':>11}  {'ref_tok%':>10}"
    )
    for thr in _THRESHOLDS:
        a = agg[thr]
        print(
            f"{thr:>9}  "
            f"{a['frac_segs_bypassed'] * 100:>11.2f}%  "
            f"{a['frac_tokens_bypassed'] * 100:>11.2f}%  "
            f"{a['frac_bypassed_are_referenced'] * 100:>10.2f}%  "
            f"{a['frac_bypassed_tokens_are_referenced'] * 100:>9.2f}%"
        )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
