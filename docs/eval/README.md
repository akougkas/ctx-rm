# ctx-rm evaluation suite

Three-tier methodology for measuring eviction-policy quality. The current
implementation covers L1 only; L2 and L3 are planned.

## Design

- **L1 — Mechanism tests.** Deterministic replay of recorded agent traces
  through `ContextBus`, no LLM. Reports eviction precision / recall,
  critical-segment retention, and churn against oracle and random controls.
  Pure functions: the same trace + policy + budget always produces the same
  metrics. Runs in CI.
- **L2 — Transcript replay** (not yet implemented). Replay a recorded trace
  and compare the context ctx-rm would have sent the model against what the
  recorded agent actually saw, measuring prompt divergence and critical-
  segment retention under counterfactual rendering.
- **L3 — Live end-to-end** (not yet implemented). Real LLM runs with
  bootstrap CIs, budget sweeps, and executable assertion checks on
  fixture repositories.

## Trace corpus

Traces are Claude Code JSONL session transcripts, discovered via
`discover_transcripts(~/.claude/projects/<project>/)`. Every `.jsonl` under
that tree is a full agent trace (main session or subagent). Currently
supported event types:

- `user` — user prompt (string content) or tool_result carrier (list content)
- `assistant` — text / thinking / tool_use blocks
- `system` — system messages
- `attachment` — dropped-in file content

Unsupported types (`permission-mode`, `file-history-snapshot`, `progress`)
are counted in `skipped_types` and ignored by the normalizer.

## Reference graph — the oracle labeler

For every segment X in a trace, we compute whether some later segment Y
references X. Two modes:

- **strict** — high-precision. Only `file_reread` and `exact_quote` edges.
- **lenient** — adds 5-token non-stopword n-gram overlap edges. Noisier but
  catches paraphrases.

From these edges we derive `is_referenced_after(seg_id, turn) -> bool`,
which is the ground-truth label for the L1 metrics. The OraclePolicy uses
the same labels to make optimal eviction decisions (upper bound).

## Metrics

| Metric | Definition |
|---|---|
| eviction precision | &#124;evicted ∩ unreferenced&#124; / &#124;evicted&#124; |
| eviction recall | &#124;evicted ∩ unreferenced&#124; / &#124;unreferenced_ever_active&#124; |
| critical_segment_retention@k | mean over turns of: fraction of segments referenced in [t+1, t+k] still in active context |
| churn_rate | fraction of evictions that got recalled |
| tokens_evicted / tokens_recalled | cost proxies |

All deltas are reported with 95% percentile-bootstrap confidence intervals
over the trace corpus (`bootstrap_mean_ci`, seed-pinned).

## Controls

- **OraclePolicy** — upper bound. Uses the reference graph to evict only
  segments that will never be referenced again; among referenced segments
  it picks the furthest-future ones first.
- **RandomPolicy** — lower bound. Uniform random selection with a fixed
  seed so runs are reproducible.

## Running it

```bash
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-ctx-rm \
    --project ctx-rm \
    --policies oracle,random,lru,clock,budget,arc,innodb \
    --budgets 8000,32000,128000 \
    --mode strict \
    --min-segments 30 \
    --json results/l1_ctxrm_strict.json
```

## Current findings (n=59 awoc traces, strict mode, budget=8000)

| policy | retention@5 | 95% CI |
|---|---|---|
| **oracle** | **0.898** | [0.871, 0.922] |
| lru / arc / innodb | 0.856 | [0.828, 0.880] |
| clock | 0.852 | [0.825, 0.878] |
| random | 0.842 | [0.812, 0.868] |
| budget | 0.815 | [0.780, 0.846] |

Key observations:

1. Oracle leaves ~4 pp of retention headroom above LRU — a real policy can
   still improve.
2. `BudgetAwarePolicy` with the default `HeuristicScorer` is statistically
   *worse* than random. The scorer penalizes `assistant` and `tool` role
   segments, which are exactly the tool_result blocks the agent will need
   again. The default scorer is mis-calibrated.
3. `LRU = ARC = InnoDB` to four decimal places. ARC's adaptive
   recency/frequency split and InnoDB's midpoint insertion reduce to LRU
   on Claude Code traces, because these traces don't exhibit the
   scan-vs-reuse pattern those policies were designed for.
4. No-pressure control (budget=128k) yields `retention@5 ≈ 0.905` for every
   policy. The ceiling below 1.0 is imposed by `ContextBus` admission
   bypass (large file_read/tool segments routed straight to Warm).

## File layout

```
src/ctx_rm/eval/
├── trace/
│   ├── schema.py              # Trace + TraceSegment models
│   ├── claude_code.py         # JSONL loader
│   ├── normalize.py           # Claude Code → canonical segments
│   └── reference_graph.py     # Oracle labeler (strict + lenient)
├── controls/
│   ├── oracle.py              # Upper-bound policy
│   └── random_policy.py       # Lower-bound policy
├── l1_mechanism/
│   ├── runner.py              # Deterministic replay through ContextBus
│   └── metrics.py             # Pure-function metric reducers
├── stats/
│   └── bootstrap.py           # Percentile bootstrap CIs
└── cli.py                     # `ctx-rm eval l1 ...`
```

Tests live under `tests/eval/` with the same structure.
