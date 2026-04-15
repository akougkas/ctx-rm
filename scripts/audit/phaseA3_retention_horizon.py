"""Phase A3: audit retention@k for signal-to-noise.

For each filtered trace, compute (turn, critical_set_size) across horizons
k ∈ {1, 3, 5, 10, all_future}. Report distribution of critical-set sizes and
the fraction of "trivial" snapshots (critical set empty, metric defaults to
1.0 and drags the mean toward 1.0 regardless of policy).

A horizon is useful if:
 - mean critical set size is >= 3 (so a 1-segment miss shifts the ratio
   by a non-trivial amount),
 - < 40% of snapshots are trivial (so the mean across snapshots isn't
   dominated by free 1.0 scores),
 - the metric spreads meaningfully across traces (std dev on the
   per-trace means).

Usage::

    python scripts/audit/phaseA3_retention_horizon.py \\
        --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \\
        --project awoc --max-traces 200 \\
        --out docs/eval/phaseA3_horizon_awoc.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript  # noqa: E402
from ctx_rm.eval.trace.normalize import normalize  # noqa: E402
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode  # noqa: E402
from ctx_rm.eval.trace.schema import TraceSegmentKind  # noqa: E402

_HORIZONS = (1, 3, 5, 10, 1_000_000)  # last value = "all future"


def _critical_sizes_for_trace(trace, graph: ReferenceGraph) -> dict[int, list[int]]:
    """For each horizon, a list of per-turn critical-set sizes.

    A "turn snapshot" here is the state at turn t after t segments have been
    ingested (we simulate the L1 runner's snapshot points). Only segments
    already ingested by turn t are counted. Pinned/system segs are excluded
    because they never leave active and would inflate every policy's score.
    """
    seg_turns = {s.seg_id: s.turn_index for s in trace.segments}
    earliest = graph._earliest_future_turn
    max_turn = trace.num_turns - 1

    result: dict[int, list[int]] = {h: [] for h in _HORIZONS}
    for t in range(max_turn + 1):
        # Segments admissible to the critical set at turn t.
        candidates: list[str] = []
        for sid, turn_in in seg_turns.items():
            if turn_in > t:
                continue
            next_ref = earliest.get(sid)
            if next_ref is None or next_ref <= t:
                continue
            candidates.append(sid)
        for h in _HORIZONS:
            count = sum(1 for sid in candidates if earliest[sid] <= t + h)
            result[h].append(count)
    return result


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(var)
    s = sorted(values)
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "min": s[0],
        "p25": s[n // 4],
        "p50": s[n // 2],
        "p75": s[(3 * n) // 4],
        "max": s[-1],
    }


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

    # Global aggregates over all snapshot critical sizes, and per-trace means.
    all_sizes: dict[int, list[int]] = {h: [] for h in _HORIZONS}
    trivial_count: dict[int, int] = {h: 0 for h in _HORIZONS}
    total_snaps: dict[int, int] = {h: 0 for h in _HORIZONS}
    per_trace_means: dict[int, list[float]] = {h: [] for h in _HORIZONS}

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
        sizes = _critical_sizes_for_trace(trace, graph)
        for h, lst in sizes.items():
            all_sizes[h].extend(lst)
            trivial_count[h] += sum(1 for v in lst if v == 0)
            total_snaps[h] += len(lst)
            if lst:
                per_trace_means[h].append(sum(lst) / len(lst))
        loaded += 1

    report: dict = {
        "corpus": str(args.trace_dir),
        "n_traces": loaded,
        "horizons": {},
    }

    for h in _HORIZONS:
        label = "all_future" if h == 1_000_000 else str(h)
        sizes = all_sizes[h]
        report["horizons"][label] = {
            "snapshot_count": total_snaps[h],
            "trivial_snapshots": trivial_count[h],
            "trivial_fraction": (trivial_count[h] / total_snaps[h]) if total_snaps[h] else 0.0,
            "critical_size_stats": _stats([float(v) for v in sizes]),
            "per_trace_mean_stats": _stats(per_trace_means[h]),
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        json.dump(report, fh, indent=2)

    print(f"traces: {loaded}")
    print(
        f"{'horizon':>10}  {'n_snaps':>8}  {'trivial%':>8}  "
        f"{'mean_size':>10}  {'p50':>6}  {'p90':>6}  {'per_trace_mean_std':>20}"
    )
    for h in _HORIZONS:
        label = "all_future" if h == 1_000_000 else str(h)
        r = report["horizons"][label]
        cs = r["critical_size_stats"]
        pm = r["per_trace_mean_stats"]
        p90_idx = int(0.9 * len(all_sizes[h])) if all_sizes[h] else 0
        p90 = sorted(all_sizes[h])[p90_idx] if all_sizes[h] else 0
        print(
            f"{label:>10}  {r['snapshot_count']:>8}  "
            f"{r['trivial_fraction'] * 100:>7.1f}%  "
            f"{cs.get('mean', 0):>10.2f}  "
            f"{cs.get('p50', 0):>6.0f}  "
            f"{p90:>6}  "
            f"{pm.get('std', 0):>20.3f}"
        )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
