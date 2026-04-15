"""Phase A1: reference-graph precision/recall audit.

Samples strict reference edges and zero-incoming targets from a corpus and
dumps them as JSONL so a human (or Claude in the loop) can label true/false
positives and false negatives. The output is deterministic under --seed.

Two audit streams:

1. ``fp`` — candidate edges drawn from ReferenceGraph.edges, stratified by
   edge kind. Each record carries both source and target content snippets
   plus metadata so the labeler can decide whether target really references
   source. Labeling the stream answers: **strict precision**.

2. ``fn`` — candidate non-edges. For every "reference-capable" target
   (tool_use with source_file, or assistant_text with >100 chars of non-
   stopword content) that has zero incoming strict edges, we emit the target
   plus its five most-recent predecessors inside the same trace so the
   labeler can decide whether any predecessor ought to have produced an
   edge. Labeling answers: **strict recall lower bound**.

Run::

    python scripts/audit/phaseA1_reference_graph.py \
        --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
        --project awoc \
        --n-traces 12 --min-segments 40 \
        --fp-per-trace 8 --fn-per-trace 4 \
        --out docs/eval/phaseA1_audit_awoc_strict.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Make src/ importable when running from repo root.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript  # noqa: E402
from ctx_rm.eval.trace.normalize import normalize  # noqa: E402
from ctx_rm.eval.trace.reference_graph import (  # noqa: E402
    ReferenceEdgeKind,
    ReferenceGraph,
    ReferenceMode,
)
from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind  # noqa: E402


@dataclass
class AuditRecord:
    kind: str  # "fp_candidate" or "fn_candidate"
    trace_id: str
    trace_path: str
    edge_kind: str | None
    source_seg_id: str | None
    source_kind: str | None
    source_turn: int | None
    source_event: int | None
    source_source_file: str | None
    source_tool_name: str | None
    source_snippet: str | None
    target_seg_id: str
    target_kind: str
    target_turn: int
    target_event: int
    target_source_file: str | None
    target_tool_name: str | None
    target_snippet: str
    neighborhood: list[dict] | None  # for fn: nearest earlier candidates


def _snippet(seg: TraceSegment, max_chars: int = 600) -> str:
    body = seg.content or ""
    if len(body) > max_chars:
        return body[:max_chars] + f" …<truncated {len(body) - max_chars} chars>"
    return body


def _summarize_seg(seg: TraceSegment, max_chars: int = 200) -> dict:
    return {
        "seg_id": seg.seg_id,
        "kind": seg.kind.value,
        "turn": seg.turn_index,
        "event": seg.event_index,
        "tool_name": seg.tool_name,
        "source_file": seg.source_file,
        "snippet": _snippet(seg, max_chars),
    }


def _stratified_sample(items: list, k: int, key, rng: random.Random) -> list:
    buckets: dict = {}
    for it in items:
        buckets.setdefault(key(it), []).append(it)
    out: list = []
    n_buckets = len(buckets) or 1
    per_bucket = max(1, k // n_buckets)
    for _, group in buckets.items():
        rng.shuffle(group)
        out.extend(group[:per_bucket])
    rng.shuffle(out)
    return out[:k]


def _is_reference_capable(seg: TraceSegment) -> bool:
    """Rough filter: segments that plausibly *should* reference earlier content.

    - A tool_use with a source_file is candidly re-reading something or
      reading a new file; only the first case should produce an incoming
      edge. We keep these as FN candidates.
    - An assistant_text block longer than ~100 non-whitespace chars almost
      always either summarizes a tool_result or cites a prior user turn.
      Anything shorter is usually chit-chat.
    - tool_result is the *source* of edges, not the target.
    """
    if seg.kind == TraceSegmentKind.TOOL_USE:
        return seg.source_file is not None
    if seg.kind == TraceSegmentKind.ASSISTANT_TEXT:
        return len((seg.content or "").strip()) >= 100
    return False


def audit_trace(
    trace: Trace,
    graph: ReferenceGraph,
    trace_path: Path,
    *,
    fp_per_trace: int,
    fn_per_trace: int,
    rng: random.Random,
) -> list[AuditRecord]:
    seg_by_id = {s.seg_id: s for s in trace.segments}
    records: list[AuditRecord] = []

    # ── FP audit: stratify by edge kind so exact_quote and file_reread
    # both get air time even when one dominates.
    edges = graph.edges
    sampled_edges = _stratified_sample(edges, fp_per_trace, lambda e: e.kind.value, rng)
    for e in sampled_edges:
        src = seg_by_id.get(e.source_seg_id)
        tgt = seg_by_id.get(e.target_seg_id)
        if src is None or tgt is None:
            continue
        records.append(
            AuditRecord(
                kind="fp_candidate",
                trace_id=trace.trace_id,
                trace_path=str(trace_path),
                edge_kind=e.kind.value,
                source_seg_id=src.seg_id,
                source_kind=src.kind.value,
                source_turn=src.turn_index,
                source_event=src.event_index,
                source_source_file=src.source_file,
                source_tool_name=src.tool_name,
                source_snippet=_snippet(src),
                target_seg_id=tgt.seg_id,
                target_kind=tgt.kind.value,
                target_turn=tgt.turn_index,
                target_event=tgt.event_index,
                target_source_file=tgt.source_file,
                target_tool_name=tgt.tool_name,
                target_snippet=_snippet(tgt),
                neighborhood=None,
            )
        )

    # ── FN audit: find reference-capable targets with zero incoming edges,
    # emit their 5 most recent earlier content-bearing predecessors as the
    # search neighborhood for manual inspection.
    incoming: dict[str, int] = {}
    for e in edges:
        incoming[e.target_seg_id] = incoming.get(e.target_seg_id, 0) + 1

    candidates: list[TraceSegment] = [
        s for s in trace.segments if _is_reference_capable(s) and incoming.get(s.seg_id, 0) == 0
    ]
    rng.shuffle(candidates)
    picked = candidates[:fn_per_trace]
    for tgt in picked:
        # Take the 5 most recent earlier tool_result / user / assistant_text /
        # tool_use segments with non-empty content.
        earlier: list[TraceSegment] = []
        for s in trace.segments:
            if s.event_index >= tgt.event_index:
                break
            if not s.content:
                continue
            if s.kind in (
                TraceSegmentKind.TOOL_RESULT,
                TraceSegmentKind.TOOL_USE,
                TraceSegmentKind.USER,
                TraceSegmentKind.ASSISTANT_TEXT,
            ):
                earlier.append(s)
        nb = [_summarize_seg(s) for s in earlier[-5:]]
        records.append(
            AuditRecord(
                kind="fn_candidate",
                trace_id=trace.trace_id,
                trace_path=str(trace_path),
                edge_kind=None,
                source_seg_id=None,
                source_kind=None,
                source_turn=None,
                source_event=None,
                source_source_file=None,
                source_tool_name=None,
                source_snippet=None,
                target_seg_id=tgt.seg_id,
                target_kind=tgt.kind.value,
                target_turn=tgt.turn_index,
                target_event=tgt.event_index,
                target_source_file=tgt.source_file,
                target_tool_name=tgt.tool_name,
                target_snippet=_snippet(tgt),
                neighborhood=nb,
            )
        )

    return records


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--trace-dir", type=Path, required=True)
    p.add_argument("--project", type=str, required=True)
    p.add_argument("--mode", type=str, default="strict", choices=["strict", "lenient"])
    p.add_argument("--n-traces", type=int, default=12)
    p.add_argument("--min-segments", type=int, default=40)
    p.add_argument("--min-turns", type=int, default=5)
    p.add_argument("--fp-per-trace", type=int, default=8)
    p.add_argument("--fn-per-trace", type=int, default=4)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    rng = random.Random(args.seed)
    paths = discover_transcripts(args.trace_dir)
    rng.shuffle(paths)

    loaded = 0
    records: list[AuditRecord] = []
    totals = {"edges": 0, "file_reread": 0, "exact_quote": 0, "ngram_overlap": 0}
    per_trace_stats: list[dict] = []

    for path in paths:
        if loaded >= args.n_traces:
            break
        try:
            lt = load_transcript(path)
            trace = normalize(lt, project=args.project)
        except Exception as exc:
            print(f"skip {path.name}: {exc}", file=sys.stderr)
            continue
        if len(trace.segments) < args.min_segments:
            continue
        if trace.num_turns < args.min_turns:
            continue
        graph = ReferenceGraph.build(trace, ReferenceMode(args.mode))
        totals["edges"] += graph.num_edges
        for e in graph.edges:
            totals[e.kind.value] = totals.get(e.kind.value, 0) + 1
        per_trace_stats.append(
            {
                "trace_id": trace.trace_id,
                "path": str(path),
                "segments": len(trace.segments),
                "turns": trace.num_turns,
                "edges": graph.num_edges,
                "referenced_segs": len(graph.referenced_seg_ids()),
            }
        )
        records.extend(
            audit_trace(
                trace,
                graph,
                path,
                fp_per_trace=args.fp_per_trace,
                fn_per_trace=args.fn_per_trace,
                rng=rng,
            )
        )
        loaded += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        fh.write(json.dumps({"meta": {"loaded": loaded, "totals": totals, "args": vars(args) | {"trace_dir": str(args.trace_dir), "out": str(args.out)}}}) + "\n")
        for tr in per_trace_stats:
            fh.write(json.dumps({"trace_stat": tr}) + "\n")
        for r in records:
            fh.write(json.dumps(asdict(r)) + "\n")

    fp_count = sum(1 for r in records if r.kind == "fp_candidate")
    fn_count = sum(1 for r in records if r.kind == "fn_candidate")
    print(
        f"traces loaded: {loaded}\n"
        f"total edges: {totals['edges']} "
        f"(file_reread={totals.get('file_reread',0)}, "
        f"exact_quote={totals.get('exact_quote',0)}, "
        f"ngram_overlap={totals.get('ngram_overlap',0)})\n"
        f"audit records: fp={fp_count} fn={fn_count}\n"
        f"wrote {args.out}"
    )


if __name__ == "__main__":
    main()
