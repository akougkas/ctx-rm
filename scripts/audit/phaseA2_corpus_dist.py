"""Phase A2: corpus distribution + inclusion filter design.

For each trace in a corpus, compute:
- segment count, turn count, total tokens, tool_use count, tool_result count,
  assistant_text count, file_reread count (count of tool_use whose source_file
  matches an earlier tool_use's source_file).

Then apply progressive inclusion filters and report how many traces survive
each step. The goal is to pick filters that keep traces that exert real
pressure on a context budget — long enough, tool-heavy enough, and with
observable re-reads so policy differences can show up.

Usage::

    python scripts/audit/phaseA2_corpus_dist.py \\
        --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \\
        --project awoc --out docs/eval/phaseA2_dist_awoc.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript  # noqa: E402
from ctx_rm.eval.trace.normalize import normalize  # noqa: E402
from ctx_rm.eval.trace.schema import TraceSegmentKind  # noqa: E402


def _percentiles(values: list[float], ps=(0.1, 0.25, 0.5, 0.75, 0.9, 0.99)) -> dict:
    if not values:
        return {}
    s = sorted(values)
    out = {}
    for p in ps:
        idx = min(len(s) - 1, int(p * len(s)))
        out[f"p{int(p * 100)}"] = s[idx]
    out["mean"] = sum(s) / len(s)
    out["max"] = s[-1]
    out["min"] = s[0]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-dir", type=Path, required=True)
    ap.add_argument("--project", type=str, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    paths = discover_transcripts(args.trace_dir)
    print(f"discovered {len(paths)} jsonl files under {args.trace_dir}")

    per_trace: list[dict] = []
    skipped = 0
    for path in paths:
        try:
            lt = load_transcript(path)
            trace = normalize(lt, project=args.project)
        except Exception as exc:  # pragma: no cover
            print(f"  skip {path.name}: {exc}", file=sys.stderr)
            skipped += 1
            continue
        kinds = Counter(s.kind.value for s in trace.segments)
        # Count file re-reads: second+ tool_use for a path we already touched.
        seen_paths: set[str] = set()
        rereads = 0
        for s in trace.segments:
            if s.kind == TraceSegmentKind.TOOL_USE and s.source_file:
                if s.source_file in seen_paths:
                    rereads += 1
                else:
                    seen_paths.add(s.source_file)
        per_trace.append(
            {
                "path": str(path),
                "trace_id": trace.trace_id,
                "segments": len(trace.segments),
                "turns": trace.num_turns,
                "tokens": trace.total_tokens,
                "tool_use": kinds.get("tool_use", 0),
                "tool_result": kinds.get("tool_result", 0),
                "assistant_text": kinds.get("assistant_text", 0),
                "user": kinds.get("user", 0),
                "system": kinds.get("system", 0),
                "file_rereads": rereads,
                "distinct_files": len(seen_paths),
                "model": trace.model,
                "cli_version": trace.cli_version,
            }
        )

    def _stats(field: str) -> dict:
        return _percentiles([t[field] for t in per_trace])

    overall = {
        "n_discovered": len(paths),
        "n_loaded": len(per_trace),
        "n_skipped": skipped,
        "segments": _stats("segments"),
        "turns": _stats("turns"),
        "tokens": _stats("tokens"),
        "tool_use": _stats("tool_use"),
        "tool_result": _stats("tool_result"),
        "assistant_text": _stats("assistant_text"),
        "file_rereads": _stats("file_rereads"),
    }

    # Progressive inclusion filter cascade. Each step reports how many traces
    # survive, so we can justify the filter choice in the paper.
    def _count(pred) -> int:
        return sum(1 for t in per_trace if pred(t))

    cascade = [
        ("all loaded", lambda t: True),
        ("segments>=20", lambda t: t["segments"] >= 20),
        ("segments>=40", lambda t: t["segments"] >= 40),
        ("segments>=80", lambda t: t["segments"] >= 80),
        ("turns>=5", lambda t: t["turns"] >= 5),
        ("turns>=10", lambda t: t["turns"] >= 10),
        ("tool_use>=5", lambda t: t["tool_use"] >= 5),
        ("tool_use>=10", lambda t: t["tool_use"] >= 10),
        ("file_rereads>=1", lambda t: t["file_rereads"] >= 1),
        ("file_rereads>=3", lambda t: t["file_rereads"] >= 3),
        (
            "RECOMMENDED (segs>=40 & turns>=8 & tool_use>=8 & rereads>=1)",
            lambda t: t["segments"] >= 40
            and t["turns"] >= 8
            and t["tool_use"] >= 8
            and t["file_rereads"] >= 1,
        ),
    ]
    filter_counts = [{"name": n, "n": _count(f)} for n, f in cascade]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        json.dump(
            {
                "overall": overall,
                "filter_cascade": filter_counts,
                "per_trace": per_trace,
            },
            fh,
            indent=2,
        )

    # Print brief summary to console.
    print(f"loaded {len(per_trace)} / {len(paths)} (skipped={skipped})")
    print("percentiles:")
    for field in ("segments", "turns", "tokens", "tool_use", "file_rereads"):
        stats = overall[field]
        print(
            f"  {field:14s} p25={stats.get('p25',0):>7} "
            f"p50={stats.get('p50',0):>7} "
            f"p75={stats.get('p75',0):>7} "
            f"p90={stats.get('p90',0):>7} "
            f"max={stats.get('max',0):>8}"
        )
    print("filter cascade:")
    for row in filter_counts:
        print(f"  {row['name']:70s} n={row['n']}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
