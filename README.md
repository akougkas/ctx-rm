# ctx-rm

Context Removal for LLM agents: a tiered-memory runtime plus a trace-replay
evaluation stack for studying eviction on real agent traces.

## Status

Phase B0 remains the published baseline milestone, and the repo now also
includes the first follow-on eval work that had been deferred after B0:

- `exact_quote` matching is tightened so the verbatim run must contain the
  gating identifier token
- `uv run ctx-rm eval l2 ...` is now implemented
- `uv run ctx-rm eval l3 ...` is now implemented
- the full repo is `ruff`-clean again

The maintained public surface in this repo is:

- `uv run ctx-rm info`
- `uv run ctx-rm eval l1 ...`
- `uv run ctx-rm eval l2 ...`
- `uv run ctx-rm eval l3 ...`

The older synthetic benchmark harness has been retired. Historical references
to `ctx-rm bench`, `ctx-rm compare`, `ctx-rm experiment`, `ctx-rm analyze`,
and `ctx-rm tasks` should not be treated as current usage.

## What ctx-rm is

ctx-rm treats context like recoverable working memory instead of a write-only
prompt buffer. New content is ingested into an active set, scored, evicted when
the token budget is tight, and preserved in lower tiers for possible recall.

The runtime pieces that implement that idea are still here:

- `ContextBus` coordinates ingest, scoring, eviction, and recall.
- `TieredStore` provides warm, cold, graveyard, and zombie tiers.
- `LRU`, `CLOCK`, `BudgetAware`, `ARC`, and `InnoDB` policies plug into the
  same bus lifecycle.
- Heuristic and sequential scorers support policy experiments.

The publication-ready part of the repo today is the evaluation stack that
replays recorded Claude Code traces through that runtime without an LLM in the
loop and measures what each policy would have kept or evicted.

## What the eval stack does

The core replay path is L1 mechanism replay:

1. Load Claude Code JSONL transcripts from a trace directory.
2. Normalize raw events into canonical `TraceSegment` records.
3. Build a per-trace `ReferenceGraph` that labels which earlier segments are
   referenced later.
4. Replay the trace once, in event order, through `ContextBus` under a chosen
   policy and token budget.
5. Reduce the replay to retention, eviction, churn, and token-cost metrics, and
   aggregate those metrics with bootstrap confidence intervals.

On top of that:

- L2 reuses the same replay inputs to measure prompt divergence against the
  recorded transcript prefix.
- L3 runs one live `AgentLoop` session through the same `ContextBus` plumbing so
  the maintained eval surface includes a real online path as well.

The main implementation lives in:

- `src/ctx_rm/eval/trace/normalize.py`
- `src/ctx_rm/eval/trace/reference_graph.py`
- `src/ctx_rm/eval/l1_mechanism/runner.py`
- `src/ctx_rm/eval/l1_mechanism/metrics.py`
- `src/ctx_rm/eval/cli.py`

Current scope:

- L1 is implemented and tested.
- L2 transcript replay is implemented and tested.
- L3 live single-run evaluation is implemented and tested.

## What changed in Phase B0

Phase B0 is the hardening pass that turned the eval stack into the baseline for
future policy work. The important changes are:

- The strict reference graph was rewritten around `file_reread`,
  `file_discovery`, and tighter `exact_quote` rules.
- The headline retention metric changed from `retention@5` to all-future
  `retention`, with `retention@10` kept as a short-horizon companion.
- Admission bypass became an explicit eval dial via `--bypass-modes on|off|both`.
- Replay now tags honest repeated `tool_result` content so ARC and InnoDB get a
  real re-access signal when previously evicted content reappears.
- The published baseline was rerun on the post-B0 stack and committed in
  `results/b0_awoc_strict.json` and `results/b0_awoc_lenient.json`.

## What changed after B0

The next round of deferred cleanup is now in-tree as well:

- `exact_quote` now requires the verbatim window itself to contain the gating
  identifier token, which removes the main divider/header false-positive path
  documented in the B0 validation writeup
- L2 now reports prompt-divergence metrics against the recorded prefix
- L3 now provides a maintained live-run entry point over `AgentLoop`
- refreshed awoc reruns are written to
  `results/phasec_awoc_strict.json` and `results/phasec_awoc_lenient.json`

## Important artifacts

These are the files a reviewer should read first:

- [`docs/eval/README.md`](docs/eval/README.md): eval-stack overview, defaults,
  commands, and artifact map.
- [`docs/eval/l1-postB0-baseline.md`](docs/eval/l1-postB0-baseline.md):
  published Phase B0 baseline on 131 awoc traces.
- [`docs/eval/phaseB-reference-graph.md`](docs/eval/phaseB-reference-graph.md):
  post-rewrite strict-graph precision audit.
- [`docs/eval/phaseB0-policy-identity.md`](docs/eval/phaseB0-policy-identity.md):
  why LRU, ARC, and InnoDB still collapse together on agent traces.
- [`docs/eval/phaseC-implementation.md`](docs/eval/phaseC-implementation.md):
  follow-on implementation summary after the B0 polish pass.
- [`results/b0_awoc_strict.json`](results/b0_awoc_strict.json) and
  [`results/b0_awoc_lenient.json`](results/b0_awoc_lenient.json): machine-readable
  baseline outputs used by the writeup.
- [`results/phasec_awoc_strict.json`](results/phasec_awoc_strict.json) and
  [`results/phasec_awoc_lenient.json`](results/phasec_awoc_lenient.json):
  refreshed reruns on the post-fix stack.
- [`docs/eval/phaseA-findings.md`](docs/eval/phaseA-findings.md): the audit
  record that motivated the B0 changes.

## Setup

`ctx-rm` requires Python 3.12+ and uses `uv`.

```bash
uv sync --extra dev --extra eval
uv run ctx-rm --help
uv run ctx-rm eval l1 --help
```

`uv run ctx-rm info` is useful for checking the local runtime environment, but
it is not required for the replay-based eval path.

## Important eval commands

### Lightweight smoke check

This runs the L1 pipeline on the committed frozen trace fixture instead of a
full corpus:

```bash
uv run ctx-rm eval l1 \
    --trace-dir tests/eval/fixtures \
    --project frozen \
    --max-traces 1 \
    --policies oracle,lru \
    --budgets 4000 \
    --mode strict \
    --bypass-modes on \
    --min-segments 0 \
    --min-turns 0 \
    --min-tool-use 0 \
    --min-rereads 0
```

### Published baseline rerun

Strict baseline:

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc \
    --max-traces 200 \
    --policies oracle,random,lru,clock,budget,arc,innodb \
    --mode strict \
    --bypass-modes both \
    --seed 0 \
    --json results/b0_awoc_strict.json
```

Lenient baseline:

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc \
    --max-traces 200 \
    --policies oracle,random,lru,clock,budget,arc,innodb \
    --mode lenient \
    --bypass-modes both \
    --seed 0 \
    --json results/b0_awoc_lenient.json
```

### Post-fix rerun

Strict:

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc \
    --max-traces 200 \
    --policies oracle,random,lru,clock,budget,arc,innodb \
    --mode strict \
    --bypass-modes both \
    --seed 0 \
    --json results/phasec_awoc_strict.json
```

Lenient:

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc \
    --max-traces 200 \
    --policies oracle,random,lru,clock,budget,arc,innodb \
    --mode lenient \
    --bypass-modes both \
    --seed 0 \
    --json results/phasec_awoc_lenient.json
```

### L2 replay

```bash
uv run ctx-rm eval l2 \
    --trace-dir tests/eval/fixtures \
    --project frozen \
    --max-traces 1 \
    --policies oracle,lru \
    --budgets 4000 \
    --mode strict \
    --bypass-modes on \
    --min-segments 0 \
    --min-turns 0 \
    --min-tool-use 0 \
    --min-rereads 0
```

### L3 live run

```bash
uv run ctx-rm eval l3 \
    --working-dir . \
    --system-prompt "You are a careful coding agent." \
    --task "Inspect the repository and summarize the current eval surface." \
    --policy budget \
    --budget 8000
```

Important CLI defaults now match the published baseline setup:

- budgets: `4000,8000,16000,32000`
- filters: `segs>=40`, `turns>=8`, `tool_use>=8`, `rereads>=1`
- bypass modes: `both`
- seed: `0`

## Metrics and controls

The L1 tables report:

- `retention`: all-future critical-segment retention
- `retention@10`: short-horizon retention
- `eviction_precision`
- `eviction_recall`
- `churn_rate`
- `tokens_evicted`

Policy controls used in the tables:

- `oracle`: upper bound under the current reference graph
- `random`: lower-bound control
- `lru`, `clock`, `budget`, `arc`, `innodb`: evaluated policies

## Repo map

```text
src/ctx_rm/core/          runtime primitives: bus, store, policies, scorers
src/ctx_rm/eval/          trace loading, reference graph, L1 replay, stats, CLI
tests/eval/               eval unit and regression tests
docs/eval/                Phase A/B0 writeups and audit artifacts
results/                  committed A5 and B0 baseline JSON outputs
```

## Developer checks

For eval and runtime changes:

```bash
uv run pytest -q
uv run ruff check src/ctx_rm tests
```

For doc-only work, validate the command surface with:

```bash
uv run ctx-rm --help
uv run ctx-rm eval l1 --help
```

## Background docs

- [`docs/tiered_graveyard.md`](docs/tiered_graveyard.md): tiering model and
  policy analogies.
- [`docs/architecture.md`](docs/architecture.md): early architectural sketch.
- [`docs/landscape.md`](docs/landscape.md): research landscape and references.

Use this README and [`docs/eval/README.md`](docs/eval/README.md) as the
authoritative starting point for current commands and the Phase B0 evaluation
story.
