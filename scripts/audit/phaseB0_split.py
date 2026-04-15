from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.schema import TraceSegmentKind


def _extract_burn_list(burn_path: Path) -> set[str]:
    """Extract trace paths from Phase A1 JSONL artifacts, write burn list if not present."""
    if burn_path.exists():
        return set(burn_path.read_text().splitlines())

    burn = set()
    for jsonl in (
        _REPO / "docs/eval/phaseA1_audit_awoc_strict.jsonl",
        _REPO / "docs/eval/phaseA1_audit_ctxrm_strict.jsonl",
    ):
        if not jsonl.exists():
            continue
        for line in jsonl.read_text().splitlines():
            rec = json.loads(line)
            if "trace_stat" in rec:
                burn.add(rec["trace_stat"]["path"])

    burn_path.parent.mkdir(parents=True, exist_ok=True)
    burn_path.write_text("\n".join(sorted(burn)) + "\n")
    return burn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-dir", type=Path, required=True)
    ap.add_argument("--project", type=str, required=True)
    ap.add_argument("--burn-list", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tuning-n", type=int, default=30)
    ap.add_argument("--validation-n", type=int, default=60)
    args = ap.parse_args()

    burn = _extract_burn_list(args.burn_list)
    all_paths = [p for p in discover_transcripts(args.trace_dir) if str(p) not in burn]

    eligible = []
    for path in all_paths:
        try:
            lt = load_transcript(path)
            trace = normalize(lt, project=args.project)
        except Exception:
            continue
        tool_uses = sum(1 for s in trace.segments if s.kind == TraceSegmentKind.TOOL_USE)
        seen, rereads = set(), 0
        for s in trace.segments:
            if s.kind == TraceSegmentKind.TOOL_USE and s.source_file:
                if s.source_file in seen:
                    rereads += 1
                else:
                    seen.add(s.source_file)
        if (
            len(trace.segments) >= 40
            and trace.num_turns >= 8
            and tool_uses >= 8
            and rereads >= 1
        ):
            eligible.append(str(path))

    rng = random.Random(args.seed)
    rng.shuffle(eligible)
    tuning = eligible[: args.tuning_n]
    validation = eligible[args.tuning_n : args.tuning_n + args.validation_n]
    remainder = eligible[args.tuning_n + args.validation_n :]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "burn_count": len(burn),
                "eligible_after_burn": len(eligible),
                "tuning": tuning,
                "validation": validation,
                "remainder_count": len(remainder),
            },
            indent=2,
        )
    )
    print(
        f"burn={len(burn)} eligible={len(eligible)} "
        f"tuning={len(tuning)} validation={len(validation)} remainder={len(remainder)}"
    )


if __name__ == "__main__":
    main()
