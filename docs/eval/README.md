# ctx-rm evaluation suite

Phase B0-ready guide to the maintained evaluation stack.

## Scope

The public eval surface today is:

- `uv run ctx-rm eval l1 ...`
- `uv run ctx-rm eval l2 ...`
- `uv run ctx-rm eval l3 ...`

Current implementation status:

- L1 mechanism replay is implemented and tested.
- L2 transcript replay is implemented and tested.
- L3 live single-run evaluation is implemented and tested.

This directory contains the audit trail and published artifacts behind the
Phase B0 baseline. Use this file as the map; use the linked writeups for the
details.

## What L1 does

L1 is deterministic trace replay through the real ctx-rm runtime:

1. Discover Claude Code JSONL transcripts under a trace directory.
2. Normalize raw events into canonical `Trace` / `TraceSegment` objects.
3. Build a `ReferenceGraph` in `strict` or `lenient` mode.
4. Replay the trace once through `ContextBus` with a chosen policy, token
   budget, and bypass setting.
5. Reduce the replay to per-trace metrics, then aggregate with 95% bootstrap
   confidence intervals across traces.

The key modules are:

- `src/ctx_rm/eval/trace/normalize.py`
- `src/ctx_rm/eval/trace/reference_graph.py`
- `src/ctx_rm/eval/l1_mechanism/runner.py`
- `src/ctx_rm/eval/l1_mechanism/metrics.py`
- `src/ctx_rm/eval/cli.py`

## What changed in Phase B0

Phase B0 hardened both the labeler and the replay story:

- strict-mode reference edges now center on `file_reread`, `file_discovery`,
  and a tighter `exact_quote` rule
- the headline metric is now all-future `retention`; `retention@10` remains as
  the short-horizon companion
- admission bypass is now explicit via `--bypass-modes on|off|both`
- replay tags honest repeated `tool_result` content reappearance so ARC and
  InnoDB can react when evicted content genuinely returns
- the awoc baseline was rerun on the post-B0 stack and committed

The old `retention@5` / 59-trace framing should be treated as historical only.

## What changed after B0

Follow-on deferred work now landed as well:

- `exact_quote` requires the matched verbatim window to contain the gating
  identifier token
- L2 is implemented as prompt-divergence replay against the recorded prefix
- L3 is implemented as a maintained live-run entry point over `AgentLoop`
- the awoc corpus has refreshed reruns in
  `results/phasec_awoc_strict.json` and `results/phasec_awoc_lenient.json`

## Current default eval settings

The CLI defaults now encode the published baseline setup:

- policies: `oracle,random,lru,clock,budget,arc,innodb`
- budgets: `4000,8000,16000,32000`
- mode: `strict` unless overridden
- bypass modes: `both`
- seed: `0`
- corpus filter: `segs>=40`, `turns>=8`, `tool_use>=8`, `rereads>=1`

The CLI prints a filter-cascade line so runs record how many traces survived
those defaults.

## Important commands

### CLI help

```bash
uv run ctx-rm eval l1 --help
```

### Fixture smoke run

Use the committed frozen trace for a fast end-to-end check:

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

### Published awoc baseline

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
    --json results/b0_awoc_strict.json
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
    --json results/b0_awoc_lenient.json
```

Those JSON outputs are already committed. Read them or the published markdown
before deciding to rerun expensive corpus jobs.

### Post-fix awoc rerun

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

## Headline Phase B0 findings

For the historical post-B0 awoc baseline:

- 131 traces survive the published filter cascade
- LRU, ARC, and InnoDB remain effectively tied on real agent traces even after
  the replay-time re-access fix
- oracle retains clear headroom at working-set budgets
- `BudgetAwarePolicy` remains weakest in strict mode at lower budgets
- strict graph hardening improved the labeler, but the B0 writeup still records
  `exact_quote` as a held-out validation limitation; the follow-on fix is
  documented separately in `phaseC-implementation.md`

See the linked docs below for the exact tables and caveats.

## Artifact map

- [`l1-postB0-baseline.md`](l1-postB0-baseline.md): published L1 baseline on
  131 awoc traces, including strict and lenient tables
- [`phaseB-reference-graph.md`](phaseB-reference-graph.md): post-rewrite
  precision audit for the strict reference graph
- [`phaseB0-policy-identity.md`](phaseB0-policy-identity.md): investigation of
  why LRU, ARC, and InnoDB collapse together on agent traces
- [`phaseC-implementation.md`](phaseC-implementation.md): concise summary of
  the post-B0 follow-on work
- [`phaseA-findings.md`](phaseA-findings.md): the pre-B0 audit that motivated
  the hardening work
- [`phaseB0_validation_split.json`](phaseB0_validation_split.json): locked
  tuning/validation split used during the graph rewrite
- [`phaseB0_audit_tuning.jsonl`](phaseB0_audit_tuning.jsonl) and
  [`phaseB0_audit_validation.jsonl`](phaseB0_audit_validation.jsonl): sampled
  audit records behind the precision writeup
- [`phaseB0_tuning_labels.md`](phaseB0_tuning_labels.md) and
  [`phaseB0_validation_labels.md`](phaseB0_validation_labels.md): human review
  notes for those sampled edges
- [`../../results/phasec_awoc_strict.json`](../../results/phasec_awoc_strict.json)
  and
  [`../../results/phasec_awoc_lenient.json`](../../results/phasec_awoc_lenient.json):
  refreshed machine-readable reruns on the post-fix stack

## Guardrails for interpretation

- The headline metric is `retention`, not `retention@5`.
- `strict` and `lenient` are both useful; they answer different precision /
  recall tradeoffs.
- the B0 validation writeup remains historically accurate for the B0 graph;
  the newer exact-quote implementation is a follow-on change and should not be
  back-read into the B0 precision document
- `results/b0_awoc_strict.json` and `results/b0_awoc_lenient.json` are the
  baseline artifacts for future policy comparisons.
