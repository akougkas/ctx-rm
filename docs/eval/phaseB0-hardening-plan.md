# Phase B0: eval-suite hardening plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to run this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal.** Turn the findings of `docs/eval/phaseA-findings.md` into a rock-solid
eval infrastructure before any Phase B policy work begins. The paper's
entire downstream argument depends on four things being correct: the
reference graph (ground truth), the retention metric (headline number),
the runner's admission control (scope of the claim), and the corpus
filter (what's actually being measured). Fix them all in one coherent
pass, with held-out validation at every step to prevent overfitting.

**Architecture.** Keep `ReferenceGraph` as a single class but refactor
its `_populate` body into per-rule private methods that can be tested in
isolation. Add a second-pass "ambient-token index" computed once per
trace and used by the tightened `exact_quote` rule. Add a new
`file_discovery` edge kind. Promote three private fields to public API
so `OraclePolicy` and `metrics.py` stop reaching into private state.
The runner gains an explicit `disable_bypass` flag that configures
ContextBus with an effectively-infinite `admission_threshold`. The CLI
changes defaults and emits one row per
(policy × budget × bypass-mode) triple.

**Tech stack.** Python 3.12, pytest, ruff, mypy strict on the six core
paths listed in `CLAUDE.md`, pydantic v2, structlog, typer, rich.

**Overfitting guardrail.** The 16 traces audited in Phase A1 are
**burned for design**: I have seen their labels and cannot use them to
tune new rules. They are recorded in `docs/eval/phaseB0-burn-traces.txt`
and excluded from the validation pool. The remaining corpus is split
with seed 1 into a **tuning set** (30 traces, usable during
implementation) and a **final validation set** (60 traces, touched
exactly once at the end). Any rule whose final-validation precision
drops below the design number is reverted, not retuned.

---

## File structure

**New files:**
- `docs/eval/phaseB0-burn-traces.txt` — list of 16 trace paths excluded from validation.
- `scripts/audit/phaseB0_graph_validation.py` — driver that builds the three trace splits, reruns the audit sampler, and writes JSONL for the labeler.
- `docs/eval/phaseB0_validation_split.json` — committed seed-1 split so the numbers are reproducible.
- `src/ctx_rm/eval/trace/_path_tokens.py` — small helper module for path-like substring detection. Isolated so it can be unit-tested without importing the graph.

**Modified files:**
- `src/ctx_rm/eval/trace/reference_graph.py` — rule rewrite, per-rule methods, public API, new `file_discovery` rule, per-trace ambient-token index.
- `src/ctx_rm/eval/controls/oracle.py` — stop accessing `_earliest_future_turn`; use public method.
- `src/ctx_rm/eval/l1_mechanism/metrics.py` — stop accessing `_earliest_future_turn`; add retention@all_future and retention@10; rename `critical_segment_retention_k5` → `critical_segment_retention`; add `critical_segment_retention_k10`; default horizon = 0 (all_future).
- `src/ctx_rm/eval/l1_mechanism/runner.py` — `L1RunConfig.disable_bypass: bool`, plumb to ContextBus.
- `src/ctx_rm/eval/cli.py` — new CLI defaults, emit bypass-on/off rows, new metric column names, new filter flags.
- `tests/eval/trace/test_reference_graph.py` — new rule tests (one test per rule, positive + negative case).
- `tests/eval/l1_mechanism/test_runner.py` — update field names; add bypass-disable coverage.
- `docs/eval/phaseA-findings.md` — leave as-is (historical record).

**Deferred files (touched only in Task 18):**
- `src/ctx_rm/core/policies/arc.py` and `innodb.py` — investigation only. No code change unless the investigation report concludes a fix is unambiguously correct.

---

## Held-out methodology (do this once, commit before any rule change)

### Task 0: Lock in the trace splits

**Files:**
- Create: `docs/eval/phaseB0-burn-traces.txt`
- Create: `scripts/audit/phaseB0_split.py`
- Create: `docs/eval/phaseB0_validation_split.json`

- [ ] **Step 1: Extract the burn list from the Phase A1 artifacts**

```python
# scripts/audit/phaseB0_split.py (partial)
import json
from pathlib import Path

BURN = set()
for jsonl in (
    "docs/eval/phaseA1_audit_awoc_strict.jsonl",
    "docs/eval/phaseA1_audit_ctxrm_strict.jsonl",
):
    for line in Path(jsonl).read_text().splitlines():
        rec = json.loads(line)
        if "trace_stat" in rec:
            BURN.add(rec["trace_stat"]["path"])
Path("docs/eval/phaseB0-burn-traces.txt").write_text(
    "\n".join(sorted(BURN)) + "\n"
)
```

- [ ] **Step 2: Write the split driver**

```python
# scripts/audit/phaseB0_split.py — full driver
import argparse, json, random, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))
from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.schema import TraceSegmentKind

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

    burn = set(args.burn_list.read_text().splitlines())
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
```

- [ ] **Step 3: Run it**

```bash
uv run python scripts/audit/phaseB0_split.py \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc \
    --burn-list docs/eval/phaseB0-burn-traces.txt \
    --out docs/eval/phaseB0_validation_split.json \
    --seed 1 --tuning-n 30 --validation-n 60
```

Expected: prints `burn=16 eligible=~418 tuning=30 validation=60 remainder=~328`.

- [ ] **Step 4: Commit**

```bash
git add docs/eval/phaseB0-burn-traces.txt scripts/audit/phaseB0_split.py \
        docs/eval/phaseB0_validation_split.json
git commit -m "eval: lock trace splits for Phase B0 graph rewrite"
```

---

## Part 1 — Reference graph rewrite

All Part 1 rules share a common style: each rule is a private method
on `ReferenceGraph` named `_rule_<something>`, called from `_populate`.
Each rule has a focused unit test in `tests/eval/trace/test_reference_graph.py`.
All rules run on the **same** trace/graph object, so later rules can
read state computed by earlier ones (e.g., the ambient-token index).

### Task 1: Add public graph API and purge private access

**Goal.** Remove every use of `graph._earliest_future_turn` outside
the class itself so subsequent refactors can't silently break callers.

**Files:**
- Modify: `src/ctx_rm/eval/trace/reference_graph.py`
- Modify: `src/ctx_rm/eval/controls/oracle.py`
- Modify: `src/ctx_rm/eval/l1_mechanism/metrics.py`
- Test: `tests/eval/trace/test_reference_graph.py` (add API test)

- [ ] **Step 1: Write failing test**

```python
# tests/eval/trace/test_reference_graph.py
class TestPublicAPI:
    def test_earliest_future_turn_returns_int_for_referenced_seg(self) -> None:
        segs = [
            _seg("tu1", 0, 0, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/a.py",
                 tool_name="Read", source_file="/a.py"),
            _seg("tu2", 3, 1, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/a.py",
                 tool_name="Read", source_file="/a.py"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert g.earliest_future_turn("tu1") == 3
        assert g.earliest_future_turn("tu2") is None
```

- [ ] **Step 2: Run test, expect AttributeError**

```bash
uv run pytest tests/eval/trace/test_reference_graph.py::TestPublicAPI -x -q
```

- [ ] **Step 3: Implement public method**

```python
# src/ctx_rm/eval/trace/reference_graph.py — add inside class ReferenceGraph
def earliest_future_turn(self, seg_id: str) -> int | None:
    """Smallest target.turn_index among edges whose source is seg_id.

    Returns None when the segment is never referenced. Callers should
    treat None as "safe to evict" under a future-only oracle."""
    return self._earliest_future_turn.get(seg_id)
```

- [ ] **Step 4: Update oracle.py**

```python
# src/ctx_rm/eval/controls/oracle.py lines 52, 70
# old: earliest = self._graph._earliest_future_turn.get(seg.seg_id)
# new: earliest = self._graph.earliest_future_turn(seg.seg_id)
```

- [ ] **Step 5: Update metrics.py**

```python
# src/ctx_rm/eval/l1_mechanism/metrics.py line ~176
# old: earliest = graph._earliest_future_turn
# new (inside the loop): next_ref = graph.earliest_future_turn(sid)
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest -q
```

Expected: all previously-passing tests still pass; new TestPublicAPI passes.

- [ ] **Step 7: Commit**

```bash
git commit -am "eval: add ReferenceGraph.earliest_future_turn public API"
```

---

### Task 2: Refactor `_populate` into per-rule methods (no behavior change)

**Goal.** Each rule becomes `_rule_file_reread`, `_rule_exact_quote`,
`_rule_ngram_overlap`. This is a pure refactor — identical edges, same
order. Next tasks modify one rule at a time without touching the others.

**Files:**
- Modify: `src/ctx_rm/eval/trace/reference_graph.py`

- [ ] **Step 1: Capture current edge signature**

```bash
uv run python -c "
from ctx_rm.eval.trace.claude_code import load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode
import json
paths = json.loads(open('docs/eval/phaseB0_validation_split.json').read())
t = normalize(load_transcript(paths['tuning'][0]), project='awoc')
g = ReferenceGraph.build(t, ReferenceMode.STRICT)
sig = sorted((e.source_seg_id, e.target_seg_id, e.kind.value) for e in g.edges)
print(f'{len(sig)} edges, hash={hash(tuple(sig))}')
" > /tmp/pre_refactor.txt
cat /tmp/pre_refactor.txt
```

- [ ] **Step 2: Split `_populate` into three methods**

```python
# src/ctx_rm/eval/trace/reference_graph.py
def _populate(self) -> None:
    self._rule_file_reread()
    self._rule_exact_quote()
    if self.mode == ReferenceMode.LENIENT:
        self._rule_ngram_overlap()

def _rule_file_reread(self) -> None:
    # Move current file_reread body verbatim here.
    ...

def _rule_exact_quote(self) -> None:
    # Move current exact_quote body verbatim here.
    ...

def _rule_ngram_overlap(self) -> None:
    # Move current lenient ngram body verbatim here.
    ...
```

- [ ] **Step 3: Rerun edge signature, confirm identical**

```bash
uv run python -c "..." > /tmp/post_refactor.txt
diff /tmp/pre_refactor.txt /tmp/post_refactor.txt
```

Expected: no difference.

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest -q
```

Expected: all tests pass, including the Phase A1 graph tests.

- [ ] **Step 5: Commit**

```bash
git commit -am "eval: refactor ReferenceGraph._populate into per-rule methods"
```

---

### Task 3: Path-token helper module

**Goal.** A single source of truth for "does this substring look like a
filesystem path token?" Used by the rewritten `exact_quote` rule to
strip path noise before gating.

**Files:**
- Create: `src/ctx_rm/eval/trace/_path_tokens.py`
- Test: `tests/eval/trace/test_path_tokens.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/eval/trace/test_path_tokens.py
from ctx_rm.eval.trace._path_tokens import (
    is_path_like,
    strip_path_segments,
)


class TestIsPathLike:
    def test_absolute_path(self) -> None:
        assert is_path_like("/home/akougkas/projects/awoc/src/cli.ts")

    def test_relative_path(self) -> None:
        assert is_path_like("./src/cli.ts")
        assert is_path_like("src/extensions/awoc-core.ts")

    def test_home_path(self) -> None:
        assert is_path_like("~/.claude/projects/foo")

    def test_plain_identifier_is_not_path(self) -> None:
        assert not is_path_like("authenticate_user_with_token")

    def test_single_slash_is_not_path(self) -> None:
        assert not is_path_like("a/b")  # too short, no extension


class TestStripPathSegments:
    def test_strips_absolute_path(self) -> None:
        text = "error in /home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py at line 42"
        stripped = strip_path_segments(text)
        assert "/home/akougkas" not in stripped
        assert "bus.py" not in stripped  # whole path token is replaced
        assert "error in" in stripped
        assert "at line 42" in stripped

    def test_preserves_code_identifiers(self) -> None:
        text = "authenticate_user_with_token returns a JWT bearer"
        stripped = strip_path_segments(text)
        assert stripped == text

    def test_strips_multiple_paths(self) -> None:
        text = "read /a/b/file.py wrote /c/d/other.ts"
        stripped = strip_path_segments(text)
        assert "file.py" not in stripped
        assert "other.ts" not in stripped
```

- [ ] **Step 2: Run tests, expect ImportError**

```bash
uv run pytest tests/eval/trace/test_path_tokens.py -x -q
```

- [ ] **Step 3: Implement `_path_tokens.py`**

```python
"""Path-token detection helpers shared by the reference graph.

`is_path_like` answers "does this string look like a filesystem path
token worth stripping from quote content?". `strip_path_segments`
replaces every path-like run inside a larger text with a single space
so downstream substring/token matching does not see path noise.

The regex matches runs that (a) contain at least one `/` separator,
(b) have at least two segments, (c) end in a segment with a `.` or an
extension-shaped suffix OR (d) start with `~/`, `./`, or `/`. It is
deliberately loose because we would rather over-strip path noise than
miss it — the quote rule re-gates on other criteria.
"""
from __future__ import annotations

import re

# One or more path segments separated by /, where each segment can
# contain [A-Za-z0-9._-]+. Must contain at least one slash.
_PATH_RE = re.compile(
    r"""
    (?:^|(?<=[\s"'`(\[<]))          # start-of-line or whitespace/quote boundary
    (?:~/|\.{1,2}/|/)?              # optional ~/, ./, ../, /
    [A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+   # at least one / between segments
    """,
    re.VERBOSE,
)


def is_path_like(s: str) -> bool:
    """True iff s looks like a filesystem path token in isolation."""
    if not s or "/" not in s:
        return False
    if len(s) < 5:
        return False
    stripped = s.strip()
    return bool(_PATH_RE.fullmatch(stripped))


def strip_path_segments(text: str) -> str:
    """Replace every path-looking run in text with a single space.

    The goal is that after stripping, neither substring matching nor
    token extraction can re-discover the path's distinctive identifiers.
    We replace with " " rather than "" so word boundaries remain intact.
    """
    return _PATH_RE.sub(" ", text)
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
uv run pytest tests/eval/trace/test_path_tokens.py -x -q
```

- [ ] **Step 5: Commit**

```bash
git commit -am "eval: add _path_tokens helper for quote-rule hardening"
```

---

### Task 4: Rewrite `_rule_exact_quote` — strip paths and bar listing sources

**Goal.** Kill the dominant FP mode (path-prefix collisions) and the
second FP mode (Glob/Grep/ls tool_results treated as quote sources).

**New rule, verbatim spec for the implementer:**

1. A segment can **emit** an exact_quote edge (be a source) only if
   - `seg.kind == TOOL_RESULT`, AND
   - its originating `tool_use.tool_name` is not in `_LISTING_TOOLS`, AND
   - its originating Bash command, if the tool is `Bash`, does not start
     with a token in `_LISTING_BASH_COMMANDS`, AND
   - the tool_result body, after `strip_path_segments`, still contains
     at least 40 characters of non-whitespace text (short results like
     "File does not exist." drop out here).
2. A segment can **receive** an exact_quote edge (be a target) only if
   - `seg.kind in (TOOL_USE, ASSISTANT_TEXT)`, AND
   - its content, after `strip_path_segments`, still contains at least
     40 characters.
3. Match runs are taken from `strip_path_segments(source.content[:4096])`
   and searched inside `strip_path_segments(target.content)`. The ≥20-char
   window and ≥8-char identifier gate run on the stripped strings only.
4. The gating identifier token must pass the **ambient-token filter**
   from Task 5 (added then, not now).

**Files:**
- Modify: `src/ctx_rm/eval/trace/reference_graph.py`
- Test: `tests/eval/trace/test_reference_graph.py`

- [ ] **Step 1: Add `_LISTING_TOOLS` and `_LISTING_BASH_COMMANDS` constants**

```python
# Tools whose output is a listing, not quotable content.
_LISTING_TOOLS = frozenset({"Glob", "Grep", "LS", "NotebookRead"})
# Bash commands whose output is a directory listing / error template.
_LISTING_BASH_COMMANDS = frozenset(
    {"ls", "find", "tree", "wc", "stat", "du", "grep", "fd", "rg"}
)
```

- [ ] **Step 2: Add test that source Glob is rejected**

```python
class TestExactQuoteSourceGuard:
    def test_glob_tool_result_is_not_a_quote_source(self) -> None:
        segs = [
            _seg("tu_glob", 0, 0, TraceSegmentKind.TOOL_USE,
                 "tool_use:Glob pattern=**/*.py",
                 tool_name="Glob", tool_use_id="g1",
                 source_file="/home/akougkas/projects/ctx-rm"),
            _seg("tr_glob", 0, 1, TraceSegmentKind.TOOL_RESULT,
                 "/home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py\n"
                 "/home/akougkas/projects/ctx-rm/src/ctx_rm/core/segment.py",
                 tool_use_id="g1"),
            _seg("tu_read", 1, 2, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py",
                 tool_name="Read", tool_use_id="r1",
                 source_file="/home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        # The Glob result must NOT produce an exact_quote edge to the Read.
        # A file_discovery edge (Task 7) would be allowed, but not exact_quote.
        assert all(e.kind != ReferenceEdgeKind.EXACT_QUOTE for e in g.edges)

    def test_short_error_result_is_not_a_quote_source(self) -> None:
        segs = [
            _seg("tu", 0, 0, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/nope.py",
                 tool_name="Read", tool_use_id="x",
                 source_file="/nope.py"),
            _seg("tr", 0, 1, TraceSegmentKind.TOOL_RESULT,
                 "File does not exist.", tool_use_id="x"),
            _seg("tu2", 1, 2, TraceSegmentKind.TOOL_USE,
                 "tool_use:Bash command=ls /nope.py",
                 tool_name="Bash", tool_use_id="b1"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert all(e.kind != ReferenceEdgeKind.EXACT_QUOTE for e in g.edges)

    def test_path_only_shared_content_is_not_an_edge(self) -> None:
        segs = [
            _seg("tr", 0, 0, TraceSegmentKind.TOOL_RESULT,
                 "Running in /home/akougkas/projects/awoc/src. "
                 "Done.",
                 tool_use_id="x"),
            _seg("tu", 1, 1, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/home/akougkas/projects/awoc/src/cli.ts",
                 tool_name="Read", tool_use_id="y",
                 source_file="/home/akougkas/projects/awoc/src/cli.ts"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        # Nothing survives stripping → no exact_quote edge, no false
        # positive. file_reread does not fire either because source_file
        # on tr is not set.
        assert g.num_edges == 0
```

- [ ] **Step 3: Run tests, expect FAIL (current code emits spurious edges)**

```bash
uv run pytest tests/eval/trace/test_reference_graph.py::TestExactQuoteSourceGuard -x -q
```

- [ ] **Step 4: Rewrite `_rule_exact_quote`**

```python
# src/ctx_rm/eval/trace/reference_graph.py
_MIN_STRIPPED_CONTENT_CHARS = 40

def _originating_tool(self, seg: TraceSegment) -> tuple[str | None, str | None]:
    """Return (tool_name, bash_leading_command) of the tool_use that produced
    this tool_result. Returns (None, None) when no link can be resolved.
    Bash command is lowercased and taken as the first whitespace-delimited token.
    """
    if seg.kind != TraceSegmentKind.TOOL_RESULT or not seg.tool_use_id:
        return (None, None)
    tu = self._tool_use_by_id.get(seg.tool_use_id)
    if tu is None:
        return (None, None)
    name = tu.tool_name
    bash_cmd: str | None = None
    if name == "Bash":
        # The stringified tool_use content is "tool_use:Bash\nargs..."
        # but the first "command=" key holds the real text.
        body = tu.content or ""
        for line in body.splitlines():
            if line.startswith("command="):
                bash_cmd = line[len("command=") :].strip().split()
                bash_cmd = bash_cmd[0].lower() if bash_cmd else None
                break
    return (name, bash_cmd)

def _is_quote_source(self, seg: TraceSegment) -> bool:
    if seg.kind != TraceSegmentKind.TOOL_RESULT:
        return False
    name, bash_cmd = self._originating_tool(seg)
    if name in _LISTING_TOOLS:
        return False
    if name == "Bash" and bash_cmd in _LISTING_BASH_COMMANDS:
        return False
    stripped = strip_path_segments(seg.content or "")
    return len(stripped.strip()) >= _MIN_STRIPPED_CONTENT_CHARS

def _is_quote_target(self, seg: TraceSegment) -> bool:
    if seg.kind not in (TraceSegmentKind.TOOL_USE, TraceSegmentKind.ASSISTANT_TEXT):
        return False
    stripped = strip_path_segments(seg.content or "")
    return len(stripped.strip()) >= _MIN_STRIPPED_CONTENT_CHARS

def _rule_exact_quote(self) -> None:
    segs = self.trace.segments
    sources: list[tuple[int, str]] = [
        (i, strip_path_segments(s.content)[:4096])
        for i, s in enumerate(segs)
        if self._is_quote_source(s)
    ]
    for i, s in enumerate(segs):
        if not self._is_quote_target(s):
            continue
        target_body = strip_path_segments(s.content)
        for j, excerpt in sources:
            if j >= i:
                break
            if self._has_quote_match(excerpt, target_body):
                src = segs[j]
                if src.seg_id != s.seg_id:
                    self._add_edge(src, s, ReferenceEdgeKind.EXACT_QUOTE)

def _has_quote_match(self, excerpt: str, target_body: str) -> bool:
    # Stage 1: find an 8+ char identifier token from excerpt that also
    # appears in target_body AND is not flagged as ambient (Task 5).
    # For Task 4 we check the base condition; Task 5 adds the ambient filter.
    gating_token: str | None = None
    for match in _TOKEN_RE.finditer(excerpt):
        tok = match.group(0)
        if len(tok) < 8 or tok.lower() in _STOPWORDS:
            continue
        if tok in target_body:
            gating_token = tok
            break
    if gating_token is None:
        return False
    # Stage 2: confirm with a ≥20-char verbatim run from excerpt.
    for start in range(0, max(1, len(excerpt) - MIN_EXACT_QUOTE_CHARS), 64):
        chunk = excerpt[start : start + MIN_EXACT_QUOTE_CHARS]
        if chunk and chunk in target_body:
            return True
    return False
```

And add the tool_use_by_id index to `_populate`:

```python
def _populate(self) -> None:
    self._tool_use_by_id: dict[str, TraceSegment] = {
        s.tool_use_id: s
        for s in self.trace.segments
        if s.kind == TraceSegmentKind.TOOL_USE and s.tool_use_id
    }
    self._rule_file_reread()
    self._rule_exact_quote()
    if self.mode == ReferenceMode.LENIENT:
        self._rule_ngram_overlap()
```

- [ ] **Step 5: Add import of strip_path_segments at top of file**

```python
from ctx_rm.eval.trace._path_tokens import strip_path_segments
```

- [ ] **Step 6: Run targeted tests**

```bash
uv run pytest tests/eval/trace/test_reference_graph.py -x -q
```

Expected: new TestExactQuoteSourceGuard passes; existing TestExactQuoteEdge still passes.

- [ ] **Step 7: Commit**

```bash
git commit -am "eval: tighten exact_quote rule — strip paths, reject listing sources"
```

---

### Task 5: Per-trace ambient-token index for exact_quote gating

**Goal.** Kill the generic-API-boilerplate FP mode by dropping any
gating identifier that appears in more than 25 % of the trace's
tool_results. This is the corpus-data-driven version of the stoplist
the user asked for: no hard-coded SDK names, no overfitting to awoc's
vocabulary, just "tokens that are ambient in this specific trace."

**Files:**
- Modify: `src/ctx_rm/eval/trace/reference_graph.py`
- Test: `tests/eval/trace/test_reference_graph.py`

- [ ] **Step 1: Write failing test**

```python
class TestAmbientTokenFilter:
    def test_identifier_in_most_results_does_not_gate_quote(self) -> None:
        # A boilerplate token that appears in every result must not gate.
        boilerplate = "SessionManager"  # 14 chars, non-stopword
        result_bodies = [
            f"SessionManager initialized. Some long unique content-A here with enough characters.",
            f"SessionManager starting. Unrelated body-B with another set of words to pad length.",
            f"SessionManager shutdown. Totally distinct body-C longer than forty characters too.",
        ]
        segs = []
        for i, body in enumerate(result_bodies):
            segs.append(_seg(f"tu{i}", i, i * 2, TraceSegmentKind.TOOL_USE,
                             "tool_use:Read file_path=/x.py", tool_name="Read",
                             tool_use_id=f"id{i}", source_file="/x.py"))
            segs.append(_seg(f"tr{i}", i, i * 2 + 1, TraceSegmentKind.TOOL_RESULT,
                             body, tool_use_id=f"id{i}"))
        # Target assistant_text mentioning SessionManager but nothing else.
        segs.append(_seg("at", 3, 999, TraceSegmentKind.ASSISTANT_TEXT,
                         "SessionManager was invoked twice."))
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        # No exact_quote edges should fire into the assistant_text just
        # because SessionManager is common.
        for e in g.edges:
            assert e.kind != ReferenceEdgeKind.EXACT_QUOTE or e.target_seg_id != "at"

    def test_distinctive_identifier_still_gates_quote(self) -> None:
        # A token that appears in only one tool_result should still gate.
        unique = "authenticate_user_with_token_v42"  # distinctive
        segs = [
            _seg("tu", 0, 0, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/auth.py", tool_name="Read",
                 tool_use_id="id1", source_file="/auth.py"),
            _seg("tr", 0, 1, TraceSegmentKind.TOOL_RESULT,
                 f"The function {unique} returns a JWT bearer token "
                 f"after validating the signature against the public key.",
                 tool_use_id="id1"),
            _seg("at", 1, 2, TraceSegmentKind.ASSISTANT_TEXT,
                 f"Looking at {unique}, it returns a JWT bearer token "
                 f"after validating the signature."),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert any(e.kind == ReferenceEdgeKind.EXACT_QUOTE for e in g.edges)
```

- [ ] **Step 2: Run tests, expect first test to FAIL, second to PASS**

```bash
uv run pytest tests/eval/trace/test_reference_graph.py::TestAmbientTokenFilter -x -q
```

- [ ] **Step 3: Add ambient-token index**

```python
# src/ctx_rm/eval/trace/reference_graph.py
_AMBIENT_MIN_RESULTS_FOR_INDEX = 4  # skip the whole filter on tiny traces
_AMBIENT_FREQUENCY_THRESHOLD = 0.25  # token in >25% of results is ambient

def _build_ambient_index(self) -> None:
    """Mark identifier tokens that appear in >25% of this trace's tool_results.

    Stored as `self._ambient_tokens: set[str]`. The set is consulted by
    `_has_quote_match` to reject any gating token that's boilerplate for
    this specific trace. This is corpus-data-driven, not a fixed stoplist.

    On traces with fewer than _AMBIENT_MIN_RESULTS_FOR_INDEX tool_results
    we skip the filter entirely — the signal is noise at that sample size.
    """
    result_segs = [
        s for s in self.trace.segments
        if s.kind == TraceSegmentKind.TOOL_RESULT and s.content
    ]
    if len(result_segs) < _AMBIENT_MIN_RESULTS_FOR_INDEX:
        self._ambient_tokens = set()
        return
    per_result_tokens: list[set[str]] = []
    for s in result_segs:
        stripped = strip_path_segments(s.content[:4096])
        toks = {
            m.group(0)
            for m in _TOKEN_RE.finditer(stripped)
            if len(m.group(0)) >= 8 and m.group(0).lower() not in _STOPWORDS
        }
        per_result_tokens.append(toks)
    counts: dict[str, int] = {}
    for toks in per_result_tokens:
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
    total = len(per_result_tokens)
    threshold = _AMBIENT_FREQUENCY_THRESHOLD * total
    self._ambient_tokens = {t for t, c in counts.items() if c > threshold}
```

And wire it into `_populate` and `_has_quote_match`:

```python
def _populate(self) -> None:
    self._tool_use_by_id = {...}
    self._build_ambient_index()        # NEW
    self._rule_file_reread()
    self._rule_exact_quote()
    if self.mode == ReferenceMode.LENIENT:
        self._rule_ngram_overlap()
```

```python
# inside _has_quote_match, modify the gating token check:
for match in _TOKEN_RE.finditer(excerpt):
    tok = match.group(0)
    if len(tok) < 8 or tok.lower() in _STOPWORDS:
        continue
    if tok in self._ambient_tokens:          # NEW
        continue
    if tok in target_body:
        gating_token = tok
        break
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
uv run pytest tests/eval/trace/test_reference_graph.py::TestAmbientTokenFilter -x -q
uv run pytest tests/eval/trace/test_reference_graph.py -q
```

- [ ] **Step 5: Commit**

```bash
git commit -am "eval: ambient-token filter for exact_quote gating"
```

---

### Task 6: Tighten `_rule_file_reread` against directory-rooted source_file

**Goal.** Kill the awoc-only FP mode where two Globs on `/awoc` with
different patterns produce an edge because both have
`source_file=/awoc`.

**Rule:** a segment participates in file_reread only if its
`source_file` has a **file-looking final component**: contains a `.`
that is not at the end, not surrounded entirely by glob metacharacters.

**Files:**
- Modify: `src/ctx_rm/eval/trace/reference_graph.py`
- Test: `tests/eval/trace/test_reference_graph.py`

- [ ] **Step 1: Write failing test**

```python
class TestFileRereadDirectoryGuard:
    def test_glob_pattern_path_does_not_create_edge(self) -> None:
        segs = [
            _seg("tu1", 0, 0, TraceSegmentKind.TOOL_USE,
                 "tool_use:Glob pattern=**/shared.ts path=/awoc",
                 tool_name="Glob", source_file="/awoc"),
            _seg("tu2", 1, 1, TraceSegmentKind.TOOL_USE,
                 "tool_use:Glob pattern=**/cli.ts path=/awoc",
                 tool_name="Glob", source_file="/awoc"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert all(e.kind != ReferenceEdgeKind.FILE_REREAD for e in g.edges)

    def test_literal_file_path_still_creates_edge(self) -> None:
        # Keep the existing positive case alive.
        segs = [
            _seg("tu1", 0, 0, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/a/b/c.py", tool_name="Read",
                 source_file="/a/b/c.py"),
            _seg("tu2", 1, 1, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/a/b/c.py", tool_name="Read",
                 source_file="/a/b/c.py"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert any(e.kind == ReferenceEdgeKind.FILE_REREAD for e in g.edges)
```

- [ ] **Step 2: Run tests, expect first FAIL**

- [ ] **Step 3: Add guard**

```python
# src/ctx_rm/eval/trace/reference_graph.py
def _is_concrete_file_path(self, path: str | None) -> bool:
    """True iff path looks like a single literal file (has a dotted leaf
    and no glob metacharacters). Directory paths, Glob patterns with
    **/x.ts, or a literal root `/` all return False.
    """
    if not path:
        return False
    if any(c in path for c in "*?[]{}"):
        return False
    leaf = path.rsplit("/", 1)[-1]
    if not leaf or "." not in leaf or leaf.startswith("."):
        # Allow dotted leafs like `.env.local` by checking for an internal dot.
        if leaf.count(".") < 1 or leaf.rfind(".") == 0:
            return False
    return True
```

And gate the file_reread loop on it:

```python
def _rule_file_reread(self) -> None:
    segs = self.trace.segments
    path_index: dict[str, list[int]] = defaultdict(list)
    tool_use_path_by_id: dict[str, str] = {}
    for i, s in enumerate(segs):
        if s.kind == TraceSegmentKind.TOOL_USE and self._is_concrete_file_path(s.source_file):
            path_index[s.source_file].append(i)
            if s.tool_use_id:
                tool_use_path_by_id[s.tool_use_id] = s.source_file
    # ... rest unchanged
```

- [ ] **Step 4: Rerun tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git commit -am "eval: require concrete file path for file_reread edges"
```

---

### Task 7: New `file_discovery` edge kind (strict recall fix)

**Goal.** Close the biggest FN hole in Phase A1: discovery-by-listing.
When an earlier tool_result body lists a file path as a standalone
token and a later tool_use reads that exact path, record the edge even
though strict file_reread cannot attribute `source_file` to the listing
segment.

**Files:**
- Modify: `src/ctx_rm/eval/trace/reference_graph.py`
- Test: `tests/eval/trace/test_reference_graph.py`

- [ ] **Step 1: Add the enum value**

```python
class ReferenceEdgeKind(StrEnum):
    FILE_REREAD = "file_reread"
    EXACT_QUOTE = "exact_quote"
    NGRAM_OVERLAP = "ngram_overlap"
    FILE_DISCOVERY = "file_discovery"   # NEW
```

- [ ] **Step 2: Write failing test**

```python
class TestFileDiscoveryEdge:
    def test_listing_to_read_creates_discovery_edge(self) -> None:
        listing = (
            "Found 3 files:\n"
            "/awoc/src/ctx_rm/core/bus.py\n"
            "/awoc/src/ctx_rm/core/segment.py\n"
            "/awoc/src/ctx_rm/core/graveyard.py\n"
        )
        segs = [
            _seg("tu_bash", 0, 0, TraceSegmentKind.TOOL_USE,
                 "tool_use:Bash\ncommand=find /awoc -name '*.py'",
                 tool_name="Bash", tool_use_id="b1"),
            _seg("tr_bash", 0, 1, TraceSegmentKind.TOOL_RESULT,
                 listing, tool_use_id="b1"),
            _seg("tu_read", 2, 2, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/awoc/src/ctx_rm/core/segment.py",
                 tool_name="Read", tool_use_id="r1",
                 source_file="/awoc/src/ctx_rm/core/segment.py"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert any(
            e.kind == ReferenceEdgeKind.FILE_DISCOVERY
            and e.source_seg_id == "tr_bash"
            and e.target_seg_id == "tu_read"
            for e in g.edges
        )

    def test_discovery_does_not_fire_on_substring_match(self) -> None:
        # The target reads "/awoc/src/ctx_rm/core/segment.py" but an earlier
        # result mentions only "/awoc/src/ctx_rm" as a prefix. No edge.
        segs = [
            _seg("tr", 0, 0, TraceSegmentKind.TOOL_RESULT,
                 "working in /awoc/src/ctx_rm directory", tool_use_id="x"),
            _seg("tu", 1, 1, TraceSegmentKind.TOOL_USE,
                 "tool_use:Read file_path=/awoc/src/ctx_rm/core/segment.py",
                 tool_name="Read", source_file="/awoc/src/ctx_rm/core/segment.py"),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert all(e.kind != ReferenceEdgeKind.FILE_DISCOVERY for e in g.edges)
```

- [ ] **Step 3: Run tests, expect FAIL**

- [ ] **Step 4: Implement `_rule_file_discovery`**

```python
_DISCOVERY_BOUNDARY_RE = re.compile(r"[^A-Za-z0-9._\-/]")

def _rule_file_discovery(self) -> None:
    """Match literal file path tokens inside earlier tool_result bodies.

    For each later tool_use with a concrete source_file P, scan every
    earlier tool_result's content for P appearing as a standalone token
    (preceded and followed by non-path-char boundaries). This catches
    agent loops where the file was discovered via `find`, `ls`, or any
    earlier listing and then read directly.
    """
    segs = self.trace.segments
    # Pre-index bodies by substring membership to avoid an O(N*M) scan.
    # Practical sizes (N<1000, M<1000) make a simple loop fine; we keep it simple.
    for i, tgt in enumerate(segs):
        if tgt.kind != TraceSegmentKind.TOOL_USE:
            continue
        p = tgt.source_file
        if not self._is_concrete_file_path(p):
            continue
        for j in range(i):
            src = segs[j]
            if src.kind != TraceSegmentKind.TOOL_RESULT or not src.content:
                continue
            if p not in src.content:
                continue
            # Enforce standalone-token boundary so `/a/b/c` in target is not
            # matched by `/a/b/c/d.py` in source.
            if self._path_is_standalone(p, src.content):
                self._add_edge(src, tgt, ReferenceEdgeKind.FILE_DISCOVERY)
                break  # one discovery edge per target is enough

def _path_is_standalone(self, path: str, body: str) -> bool:
    idx = 0
    while True:
        k = body.find(path, idx)
        if k == -1:
            return False
        left_ok = k == 0 or bool(_DISCOVERY_BOUNDARY_RE.match(body[k - 1]))
        right_end = k + len(path)
        right_ok = right_end == len(body) or bool(
            _DISCOVERY_BOUNDARY_RE.match(body[right_end])
        )
        if left_ok and right_ok:
            return True
        idx = k + 1
```

Wire into `_populate`:

```python
def _populate(self) -> None:
    self._tool_use_by_id = {...}
    self._build_ambient_index()
    self._rule_file_reread()
    self._rule_file_discovery()         # NEW
    self._rule_exact_quote()
    if self.mode == ReferenceMode.LENIENT:
        self._rule_ngram_overlap()
```

- [ ] **Step 5: Rerun tests, expect PASS**

```bash
uv run pytest tests/eval/trace/test_reference_graph.py -q
```

- [ ] **Step 6: Commit**

```bash
git commit -am "eval: add file_discovery edge kind for listing-based references"
```

---

### Task 8: Validation audit — run precision on tuning set, iterate, then final pass

**Goal.** Confirm precision ≥ 0.90 on unseen traces. If below, tighten
the rules; if the validation number is lower than the tuning number by
more than two standard errors, accept the validation number and revisit
the rules.

**Files:**
- Modify: `scripts/audit/phaseA1_reference_graph.py` (add --paths-file flag)
- Create: `docs/eval/phaseB0_audit_tuning.jsonl`
- Create: `docs/eval/phaseB0_audit_validation.jsonl`

- [ ] **Step 1: Add `--paths-file` option to the audit sampler**

```python
# scripts/audit/phaseA1_reference_graph.py — inside main()
p.add_argument("--paths-file", type=Path, default=None,
               help="JSON or text file of trace paths; overrides --trace-dir walk")
# After computing `paths = discover_transcripts(args.trace_dir)`:
if args.paths_file is not None:
    raw = args.paths_file.read_text()
    if args.paths_file.suffix == ".json":
        blob = json.loads(raw)
        paths = [Path(p) for p in blob.get("tuning", []) + blob.get("validation", [])]
    else:
        paths = [Path(line) for line in raw.splitlines() if line.strip()]
```

Add a second flag to select one subset:

```python
p.add_argument("--split", choices=("tuning", "validation", "all"), default="all")
# ...
if args.paths_file is not None and args.paths_file.suffix == ".json":
    blob = json.loads(raw)
    if args.split == "all":
        paths = [Path(p) for p in blob["tuning"] + blob["validation"]]
    else:
        paths = [Path(p) for p in blob[args.split]]
```

- [ ] **Step 2: Run tuning audit on the 30-trace tuning split**

```bash
uv run python scripts/audit/phaseA1_reference_graph.py \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc --mode strict \
    --paths-file docs/eval/phaseB0_validation_split.json --split tuning \
    --n-traces 30 --fp-per-trace 8 --fn-per-trace 4 --seed 0 \
    --out docs/eval/phaseB0_audit_tuning.jsonl
```

- [ ] **Step 3: Dispatch the labeling subagent against tuning set**

Use the same rubric from Phase A1 labeling. Subagent output goes to
`docs/eval/phaseB0_tuning_labels.md`. If precision < 0.90:

1. Re-read the top failure modes from the labels.
2. Adjust rules (new task inline; do not skip the test-first flow).
3. Re-run the tuning audit.
4. Re-label.
5. Stop iterating when tuning precision ≥ 0.90 OR you've tightened the
   rules to a point where the test in Task 4/5/6/7 is at risk of
   regressing. If you regress a test, you went too far.

- [ ] **Step 4: Run validation audit exactly once**

```bash
uv run python scripts/audit/phaseA1_reference_graph.py \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc --mode strict \
    --paths-file docs/eval/phaseB0_validation_split.json --split validation \
    --n-traces 60 --fp-per-trace 6 --fn-per-trace 3 --seed 2 \
    --out docs/eval/phaseB0_audit_validation.jsonl
```

Note the different `--seed` so the sampler picks different records than
the tuning run, and the smaller `--fp-per-trace` so the total labeling
load is ~360 FP + 180 FN across 60 traces.

- [ ] **Step 5: Dispatch labeling subagent against validation set**

Subagent output goes to `docs/eval/phaseB0_validation_labels.md`.

- [ ] **Step 6: Write `docs/eval/phaseB-reference-graph.md`**

Reports:
- Old precision (pooled from Phase A1): 0.602 overall, 0.875 file_reread,
  0.477 exact_quote.
- Tuning precision and per-rule breakdown.
- Validation precision and per-rule breakdown.
- Absolute gap to the 0.90 target.
- Any rules dropped or reverted during iteration.

- [ ] **Step 7: Commit**

```bash
git add scripts/audit/phaseA1_reference_graph.py \
        docs/eval/phaseB0_audit_{tuning,validation}.jsonl \
        docs/eval/phaseB0_{tuning,validation}_labels.md \
        docs/eval/phaseB-reference-graph.md
git commit -m "eval: reference graph validation audit — precision XX on held-out set"
```

---

## Part 2 — Retention metric

### Task 9: Swap retention@5 for retention@all_future + retention@10

**Files:**
- Modify: `src/ctx_rm/eval/l1_mechanism/metrics.py`
- Modify: `src/ctx_rm/eval/cli.py`
- Modify: `tests/eval/l1_mechanism/test_runner.py`

- [ ] **Step 1: Write failing test**

```python
# tests/eval/l1_mechanism/test_runner.py — new test
def test_metrics_report_all_future_and_k10(build_tiny_result):
    result, trace, graph = build_tiny_result()  # existing helper
    m = compute_metrics(result, trace, graph)
    assert hasattr(m, "critical_segment_retention")
    assert hasattr(m, "critical_segment_retention_k10")
    assert 0.0 <= m.critical_segment_retention <= 1.0
    assert 0.0 <= m.critical_segment_retention_k10 <= 1.0
```

(If the test_runner.py tests use inline fixtures rather than a helper,
inline the Trace construction.)

- [ ] **Step 2: Run test, expect AttributeError**

- [ ] **Step 3: Update L1Metrics and compute_metrics**

```python
# src/ctx_rm/eval/l1_mechanism/metrics.py
@dataclass
class L1Metrics:
    # ... existing fields ...
    critical_segment_retention: float       # horizon = all_future (was _k5)
    critical_segment_retention_k10: float   # short-horizon companion

    def as_row(self) -> dict:
        return {
            # ...
            "retention": self.critical_segment_retention,
            "retention_k10": self.critical_segment_retention_k10,
        }

_ALL_FUTURE_HORIZON = 10**9  # "every future turn"

def compute_metrics(
    result: L1Result,
    trace: Trace,
    graph: ReferenceGraph,
) -> L1Metrics:
    # ... existing body ...
    retention_all = _critical_segment_retention(
        result, trace, graph, horizon=_ALL_FUTURE_HORIZON
    )
    retention_k10 = _critical_segment_retention(
        result, trace, graph, horizon=10
    )
    return L1Metrics(
        # ...
        critical_segment_retention=retention_all,
        critical_segment_retention_k10=retention_k10,
    )
```

And update the `_critical_segment_retention` helper to use the public
API added in Task 1:

```python
def _critical_segment_retention(
    result: L1Result,
    trace: Trace,
    graph: ReferenceGraph,
    *,
    horizon: int,
) -> float:
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
```

- [ ] **Step 4: Update CLI table column**

```python
# src/ctx_rm/eval/cli.py around line 208
ret_all = bootstrap_mean_ci([c.critical_segment_retention for c in cell], seed=seed)
ret_k10 = bootstrap_mean_ci([c.critical_segment_retention_k10 for c in cell], seed=seed)
# replace "retention@5" column with "retention" and add "retention@10" column
```

- [ ] **Step 5: Fix existing tests that reference `critical_segment_retention_k5`**

```bash
uv run pytest tests/eval/l1_mechanism/test_runner.py -q
```

Replace the two references in `test_runner.py` with
`critical_segment_retention` (the no-horizon field).

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest -q
```

- [ ] **Step 7: Commit**

```bash
git commit -am "eval: headline metric is retention@all_future; add retention@10"
```

---

## Part 3 — Runner admission-bypass control

### Task 10: `L1RunConfig.disable_bypass` plumbed through ContextBus

**Files:**
- Modify: `src/ctx_rm/eval/l1_mechanism/runner.py`
- Modify: `src/ctx_rm/eval/cli.py`
- Test: `tests/eval/l1_mechanism/test_runner.py`

- [ ] **Step 1: Write failing test**

```python
# tests/eval/l1_mechanism/test_runner.py
def test_disable_bypass_keeps_large_tool_results_active():
    # Craft a trace with a single large tool_result (>2000 tokens).
    large_body = "x " * 2500  # ~5000 tokens via estimator
    trace = Trace(
        trace_id="t", source_path="m", project="p",
        segments=[
            TraceSegment(seg_id="u", turn_index=0, event_index=0, timestamp=0.0,
                         kind=TraceSegmentKind.USER, content="hello world" * 20,
                         token_count=50),
            TraceSegment(seg_id="tu", turn_index=0, event_index=1, timestamp=0.0,
                         kind=TraceSegmentKind.TOOL_USE, content="tool_use:Read",
                         token_count=10, tool_use_id="r1"),
            TraceSegment(seg_id="tr", turn_index=0, event_index=2, timestamp=0.0,
                         kind=TraceSegmentKind.TOOL_RESULT, content=large_body,
                         token_count=2500, tool_use_id="r1"),
            TraceSegment(seg_id="at", turn_index=1, event_index=3, timestamp=0.0,
                         kind=TraceSegmentKind.ASSISTANT_TEXT, content="done", token_count=5),
        ],
    )
    graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
    for disable in (False, True):
        cfg = L1RunConfig(
            trace=trace, reference_graph=graph,
            policy_factory=lambda g: LRUPolicy(),
            policy_name="lru", token_budget=100_000,
            disable_bypass=disable,
        )
        result = run_l1(cfg)
        active_at_end = set(result.snapshots[-1].active_seg_ids)
        if disable:
            assert "tr" in active_at_end
        else:
            assert "tr" not in active_at_end
```

- [ ] **Step 2: Run test, expect failure on missing arg**

- [ ] **Step 3: Add the field and plumb it**

```python
# src/ctx_rm/eval/l1_mechanism/runner.py
@dataclass
class L1RunConfig:
    trace: Trace
    reference_graph: ReferenceGraph
    policy_factory: Callable[[ReferenceGraph], EvictionPolicy]
    policy_name: str
    token_budget: int
    headroom_ratio: float = 0.15
    scorer: Scorer | None = None
    pin_system: bool = True
    disable_bypass: bool = False  # NEW
```

```python
# in run_l1, replace the bus construction:
import sys
admission_threshold = sys.maxsize if config.disable_bypass else 2000
bus = ContextBus(
    token_budget=config.token_budget,
    store=store,
    policy=policy,
    scorer=config.scorer,
    headroom_ratio=config.headroom_ratio,
    admission_threshold=admission_threshold,
    on_event=on_event,
)
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git commit -am "eval: L1RunConfig.disable_bypass flag plumbs to ContextBus admission"
```

---

### Task 11: CLI emits one row per bypass mode

**Files:**
- Modify: `src/ctx_rm/eval/cli.py`

- [ ] **Step 1: Add CLI flag**

```python
@app.command("l1")
def cmd_l1(
    # ... existing args ...
    bypass_modes: str = typer.Option(
        "both",
        "--bypass-modes",
        help="Comma-separated subset of {on,off,both}. Controls whether "
             "the runner disables ContextBus admission bypass. 'both' emits "
             "two rows per (policy, budget) pair.",
    ),
    # ...
):
```

- [ ] **Step 2: Expand the run loop to iterate over bypass modes**

```python
mode_values = _parse_csv(bypass_modes)
if "both" in mode_values:
    mode_values = ["on", "off"]

for trace, graph in traces_and_graphs:
    for budget in budget_values:
        for name in policy_names:
            for mode in mode_values:
                factory = _POLICY_REGISTRY[name]
                def _make(g, _f=factory, _b=budget):
                    return _f(g, _b)
                cfg = L1RunConfig(
                    trace=trace,
                    reference_graph=graph,
                    policy_factory=_make,
                    policy_name=name,
                    token_budget=budget,
                    scorer=HeuristicScorer() if name == "budget" else None,
                    disable_bypass=(mode == "off"),
                )
                result = run_l1(cfg)
                row = compute_metrics(result, trace, graph)
                row_dict = row.as_row()
                row_dict["bypass"] = mode
                rows.append(row_dict)
```

The existing table renderer needs a small change: key the per-cell
aggregation on `(budget, policy, bypass)` instead of `(budget, policy)`,
and print a separate table per `bypass` value (or add a column).
Simplest: print one table per budget per bypass mode.

- [ ] **Step 3: Manual CLI smoke test**

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc --policies lru --budgets 8000 --mode strict \
    --min-segments 40 --max-traces 10 --bypass-modes both
```

Expected: two tables ("bypass=on" and "bypass=off"), one row each for
LRU, differing retention numbers.

- [ ] **Step 4: Commit**

```bash
git commit -am "eval: CLI emits separate tables for bypass-on and bypass-off"
```

---

## Part 4 — CLI defaults

### Task 12: Update filter, budget grid, and require reproducibility

**Files:**
- Modify: `src/ctx_rm/eval/cli.py`

- [ ] **Step 1: Change defaults**

```python
min_segments: int = typer.Option(40, "--min-segments"),
min_turns: int = typer.Option(8, "--min-turns"),
min_tool_use: int = typer.Option(8, "--min-tool-use"),
min_rereads: int = typer.Option(1, "--min-rereads"),
budgets: str = typer.Option("4000,8000,16000,32000", "--budgets"),
```

- [ ] **Step 2: Apply the new filter**

```python
def _passes_filter(trace: Trace) -> bool:
    if len(trace.segments) < min_segments:
        return False
    if trace.num_turns < min_turns:
        return False
    tool_uses = sum(1 for s in trace.segments if s.kind == TraceSegmentKind.TOOL_USE)
    if tool_uses < min_tool_use:
        return False
    seen, rereads = set(), 0
    for s in trace.segments:
        if s.kind == TraceSegmentKind.TOOL_USE and s.source_file:
            if s.source_file in seen:
                rereads += 1
            else:
                seen.add(s.source_file)
    return rereads >= min_rereads
```

- [ ] **Step 3: Emit a "filter cascade" line in the CLI output**

```python
console.print(
    f"filter: segs>={min_segments} turns>={min_turns} "
    f"tool_use>={min_tool_use} rereads>={min_rereads}"
)
console.print(f"  using {len(traces_and_graphs)} / {len(paths)} traces")
```

- [ ] **Step 4: Smoke test**

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc --max-traces 20 --policies oracle,lru --bypass-modes off
```

Expected: produces a clean table at the new defaults.

- [ ] **Step 5: Commit**

```bash
git commit -am "eval: CLI defaults — corpus filter and budget grid from Phase A"
```

---

## Part 5 — Rerun and publish new L1 baseline

### Task 13: Full L1 rerun on awoc, commit numbers

**Files:**
- Create: `docs/eval/l1-postB0-baseline.md`
- Create: `results/b0_awoc_strict.json`, `results/b0_awoc_lenient.json`

- [ ] **Step 1: Run strict, bypass both, new budget grid**

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc \
    --policies oracle,random,lru,clock,budget,arc,innodb \
    --budgets 4000,8000,16000,32000 \
    --mode strict \
    --max-traces 200 \
    --bypass-modes both \
    --seed 0 \
    --json results/b0_awoc_strict.json
```

- [ ] **Step 2: Run lenient variant**

```bash
# same invocation but --mode lenient --json results/b0_awoc_lenient.json
```

- [ ] **Step 3: Write `docs/eval/l1-postB0-baseline.md`**

For each (budget, bypass-mode, ref-mode) combination, a policy-vs-policy
table with retention, retention@10, eviction precision, eviction recall,
churn rate, and a 95 % bootstrap CI on every cell. Call out the
comparisons where the hardened graph changes the ordering.

- [ ] **Step 4: Commit**

```bash
git add results/b0_awoc_*.json docs/eval/l1-postB0-baseline.md
git commit -m "eval: post-B0 L1 baseline on awoc (strict + lenient, both bypass modes)"
```

---

## Part 6 — LRU / ARC / InnoDB investigation

### Task 14: Understand why three policies produce identical outputs

**Files:**
- Read-only: `src/ctx_rm/core/policies/{lru,arc,innodb}.py`
- Create: `docs/eval/phaseB0-policy-identity.md`

- [ ] **Step 1: Reproduce the identity at finer granularity**

```bash
uv run python -c "
from ctx_rm.eval.trace.claude_code import load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode
from ctx_rm.eval.l1_mechanism.runner import L1RunConfig, run_l1
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.policies.arc import ARCPolicy
from ctx_rm.core.policies.innodb import InnoDBPolicy
import json
sp = json.loads(open('docs/eval/phaseB0_validation_split.json').read())
path = sp['tuning'][0]
trace = normalize(load_transcript(path), project='awoc')
graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
results = {}
for name, factory in (
    ('lru', lambda g: LRUPolicy()),
    ('arc', lambda g: ARCPolicy(capacity_tokens=8000)),
    ('innodb', lambda g: InnoDBPolicy(capacity_tokens=8000)),
):
    r = run_l1(L1RunConfig(trace=trace, reference_graph=graph,
                           policy_factory=factory, policy_name=name,
                           token_budget=8000, disable_bypass=True))
    results[name] = [sid for sid, _ in r.evictions]
print('lru == arc:', results['lru'] == results['arc'])
print('lru == innodb:', results['lru'] == results['innodb'])
print('num evictions:', len(results['lru']))
print('first 10 ids:', results['lru'][:10])
"
```

- [ ] **Step 2: Read each policy's `on_ingest` / `on_evict` / `select_evictions`**

Hypothesis to confirm: on agent traces L1 never issues recalls, so ARC's
B1/B2 ghost hits never fire, so `p` never moves from 0, so ARC's
selection reduces to "drain T1 oldest-first" — which is LRU. InnoDB is
likely similar.

- [ ] **Step 3: Write `docs/eval/phaseB0-policy-identity.md`**

Two sections:
1. **Mechanism.** Why LRU = ARC = InnoDB on these traces, with line-level
   citations into `arc.py` / `innodb.py`. Include the bit of state that
   *would* have differentiated the policies (e.g., `p` in ARC) and the
   exact code path that leaves it at the default.
2. **Decision.** One of:
    - (a) **Degeneracy is real, publish it.** The paper reports
      "LRU/ARC/InnoDB identical on agent traces because they lack the
      re-access signal these algorithms need" as a finding.
    - (b) **Fix the signal.** Track in-trace re-reads by content hash
      rather than seg_id, feed them to ARC's ghost-list logic as if they
      were recalls. Only do this if the new signal is provably honest
      (no oracle leakage).
    - (c) **Drop the policies from the main table.** Keep them in the
      code for non-agent workloads, do not feature in the paper.

Choose one. Document the decision.

- [ ] **Step 4: If the decision is (b), open a new task inline with TDD.**
      If the decision is (a) or (c), commit the note and move on.

- [ ] **Step 5: Commit**

```bash
git add docs/eval/phaseB0-policy-identity.md [any code changes]
git commit -m "eval: document LRU=ARC=InnoDB degeneracy on agent traces"
```

---

## Part 7 — Test suite & CI integration

### Task 15: Freeze a tiny trace sample for L1 regression

**Files:**
- Create: `tests/eval/fixtures/frozen_trace.json` (hand-copied small awoc trace)
- Create: `tests/eval/l1_mechanism/test_l1_regression.py`

- [ ] **Step 1: Pick a small tuning trace (~60 segments) and commit it**

```bash
uv run python -c "
import json
sp = json.loads(open('docs/eval/phaseB0_validation_split.json').read())
for p in sp['tuning']:
    import subprocess
    # copy the JSONL under tests/eval/fixtures/ — small one first
    ...
" > /dev/null
# Inspect, pick one, commit as frozen_trace.jsonl
```

- [ ] **Step 2: Write regression test**

```python
# tests/eval/l1_mechanism/test_l1_regression.py
EXPECTED_RETENTION_LRU_BYPASS_OFF = 0.xxx   # filled in after first run
EXPECTED_RETENTION_ORACLE_BYPASS_OFF = 0.yyy

def test_frozen_l1_numbers():
    path = Path("tests/eval/fixtures/frozen_trace.jsonl")
    trace = normalize(load_transcript(path), project="awoc")
    graph = ReferenceGraph.build(trace, ReferenceMode.STRICT)
    cfg_lru = L1RunConfig(trace=trace, reference_graph=graph,
                          policy_factory=lambda g: LRUPolicy(),
                          policy_name="lru", token_budget=8000,
                          disable_bypass=True)
    m = compute_metrics(run_l1(cfg_lru), trace, graph)
    assert abs(m.critical_segment_retention - EXPECTED_RETENTION_LRU_BYPASS_OFF) < 1e-9
    # Repeat for oracle.
```

- [ ] **Step 3: Fill in the expected numbers by running the test once**

- [ ] **Step 4: Run full test suite, ensure green**

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy src/ctx_rm/config.py src/ctx_rm/core/bus.py \
    src/ctx_rm/drivers/llamacpp.py src/ctx_rm/agents/loop.py \
    src/ctx_rm/benchmarks/runner.py src/ctx_rm/cli/main.py
```

Expected: all green. (mypy paths are the six locked in `CLAUDE.md`.)

Wait — the benchmarks paths no longer exist after the earlier purge.
Check and update the mypy target list if necessary. This may have
already been a pre-existing issue; report it rather than silently fix.

- [ ] **Step 5: Commit**

```bash
git commit -am "test: frozen L1 regression + full suite green"
```

---

## Self-review checklist (run after the plan is written)

1. **Spec coverage.** Walk through `docs/eval/phaseA-findings.md` section
   by section. Every `Decision`, `Implication`, and `Blocker` from
   Phase A must map to a task here.
    - A1 graph fix → Tasks 3–8. ✓
    - A1 public API → Task 1. ✓
    - A2 corpus filter → Task 12. ✓
    - A3 retention metric → Task 9. ✓
    - A4 bypass flag → Tasks 10, 11. ✓
    - A5 strict/lenient rerun → Task 13. ✓
    - B5 (BudgetAware) → deferred per brief ("fix every finding" does
      not override the user's explicit two-phase split; BudgetAware's
      fix needs cross-validated role-weight relearning and belongs in
      Phase B proper, not the hardening pass). Flagged for the user.
    - B6 (LRU/ARC/InnoDB) → Task 14. ✓
2. **Placeholder scan.** No TBD/TODO/ellipsis-as-content. Every code
   block is the exact text to drop in.
3. **Type consistency.** `disable_bypass`, `critical_segment_retention`,
   `earliest_future_turn`, `_rule_*` names used consistently across
   tasks.
4. **Test-first order.** Every behavior-changing task writes its test
   before the implementation step.
5. **Commits granular.** One task, one commit, with a message that
   describes the change in the same tense as the repo's existing
   `git log`.

---

## Risk / assumption log

- **Assumption: the existing `test_runner.py` can tolerate the metric
  rename.** If the file builds fresh Trace objects inline without a
  helper, Task 9 requires editing the two existing assertions.
  Confirmed by search in the implementation prep: lines 159 and 218
  both reference `critical_segment_retention_k5`.
- **Assumption: the LLM labeler is a calibrated oracle.** Both Phase A1
  labelers agreed on the dominant failure modes, which is weak but
  nonzero evidence of inter-rater agreement. If Task 8's validation
  audit produces a precision number I find suspicious, I will dispatch a
  second independent labeler on a random 20-record slice and use
  disagreement as a noise estimate.
- **Assumption: `bash_leading_command` parsing in Task 4 handles the
  stringified tool_use format.** Content is `tool_use:Bash\ncommand=<cmd>`
  per `normalize._stringify_tool_use`. The helper splits on `command=`
  which matches this format exactly. I am **not** assuming Bash
  commands never include `command=` in the body.
- **Risk: Task 5's 25 % ambient threshold is arbitrary.** I picked 0.25
  because at >25 % a token is in more than a quarter of the trace's
  tool_results and is almost certainly a header, import, or common
  call. If tuning audit precision is still below 0.90, the fallback is
  to drop to 0.15 **on the tuning set** and rerun validation. Do not
  retune against validation.
- **Risk: `file_discovery` could over-generate on traces with heavy
  listings.** Mitigation: boundary-check enforced in
  `_path_is_standalone`. Tuning audit will tell us if the overall
  precision drops; if so, require P to be at least 12 characters long
  before emitting the edge.
- **Out of scope.** No changes to the runtime `Scorer`, `ContextBus`
  eviction internals, `Segment` model, or storage layer beyond the
  `admission_threshold` wiring. No Phase B BudgetAware fix. No new
  policies.

---

## After this plan lands

The eval infrastructure is "trusted enough to measure policies" — not
"ready to publish." Phase B then uses the hardened suite to:

- B5 (now unblocked): redesign BudgetAware's scoring with
  cross-validated role weights learned from reference-graph labels.
- B6 continuation: if Task 14 chose (b), implement the honest-signal
  ARC fix. If (a)/(c), no-op.
- B7 (still deferred): content-aware admission policy as an innovation.
- Phase C: L2 counterfactual-rendering replay.
- Phase D: paper-grade innovation write-up, ablations, reproducibility
  script.

Phase B0 is closed when every checkbox above is ticked, every artifact
is committed, and `docs/eval/l1-postB0-baseline.md` exists with the
re-run numbers and a one-paragraph note about how they compare to the
pre-B0 baseline.
