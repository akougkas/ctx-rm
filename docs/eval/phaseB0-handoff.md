# Phase B0 handoff — continue in a fresh Claude Code session

Copy everything below the `---` into the first message of a new Claude
Code session opened on this project. No superpowers skills needed. Use
normal subagent dispatch: **haiku for codebase exploration, sonnet for
implementation, opus only for design/review decisions on the two
high-stakes tasks flagged below.**

---

You are resuming Phase B0 of ctx-rm — the eval-suite hardening pass
that must land before any Phase B policy work. Prior sessions did
Phase A (audit) and started Phase B0 (infrastructure rewrite). Four
tasks are committed on branch `phase-b0-hardening`. Twelve remain.

## Where to start

Work from: `/home/akougkas/projects/ctx-rm/.worktrees/phase-b0-hardening`
Branch: `phase-b0-hardening` (a worktree off `main`; do not switch branches)
Python: `uv run ...` (never bare `python`)
Baseline: **169 tests passing, ruff clean on `src/ctx_rm/eval/` and `tests/eval/`.**

### Files to read on session start, in this order

1. `docs/eval/phaseA-findings.md` — **why** we are doing this. The five
   audit subsections (A1–A5) are the evidence base for every rule
   change in B0. Do not re-litigate Phase A findings; they are locked.
2. `docs/eval/phaseB0-hardening-plan.md` — the **full task spec** for
   all 16 tasks (T0–T15). Tasks 0–3 are done; T4–T15 are your work.
   Each task in the plan has exact file paths, exact code snippets,
   exact test assertions, and a commit message. Follow them literally
   where given.
3. `docs/eval/phaseB0_validation_split.json` — the locked train/test
   split. Use `tuning[0:30]` to iterate rule changes, touch
   `validation[0:60]` exactly once in Task 8.
4. `CLAUDE.md` (project root) — coding conventions. Key rules:
   `from __future__ import annotations`, `X | Y` unions, absolute
   imports, Google-style docstrings, no `__all__`, ruff E,F,I,N,W,UP,B,SIM,RUF,
   line-length 100. Never write `[noun] - [clause]` sentences; they are
   banned in prose and code comments.

### Commit log so far on this branch

```
2e66faa eval: path-token boundary set + docstring fix
57cdef7 eval: add _path_tokens helper for quote-rule hardening
c6d8fa9 eval: refactor ReferenceGraph._populate into per-rule methods
cc49721 eval: add ReferenceGraph.earliest_future_turn public API
f17d442 eval: phaseB0_split lint/docstring/error-logging polish
442f55f eval: lock trace splits for Phase B0 graph rewrite
```

## The three hard rules (non-negotiable)

1. **No cheating.** Do not inflate ctx-rm's lead by tuning metrics to
   the corpus, by cherry-picking traces, or by using the oracle's
   ground truth inside a "real" policy. Every gain must come from a
   real improvement to how the system scores, evicts, recalls, or
   adapts.
2. **Apples to apples.** Every policy comparison fixes every variable
   except the policy. Same trace, same seed, same reference graph,
   same budget, same admission rules, same segment constructor.
3. **Optimize the codebase, not the benchmark.** If a finding shows a
   policy is weak, fix the policy. If a finding shows a metric is
   weak, replace the metric and regenerate every prior table. Never
   tune the test to hide the gap.

## Overfitting guardrail

The 16 traces used in Phase A1 labeling are "burned" — listed in
`docs/eval/phaseB0-burn-traces.txt`, already excluded from the split.
When iterating rule tweaks in T4–T7, you may look at labeled records
from the **tuning set** (30 traces, seed 1). When measuring final
precision in T8, you audit the **validation set** (60 traces) exactly
once with no further rule changes. If validation precision is lower
than tuning by more than ~5 percentage points, accept the validation
number and report it — do NOT re-tune.

## Remaining tasks

Each task's full spec lives in `docs/eval/phaseB0-hardening-plan.md`
under the matching heading. Treat the plan as canonical; this list is
a navigation aid.

### Task 4 — rewrite `_rule_exact_quote`

**Goal:** kill path-prefix-collision FPs (~40 of the Phase A1 bad
edges) and listing-source FPs (~10) by stripping path tokens and
rejecting Glob/Grep/LS/NotebookRead results (plus Bash find/ls/wc/grep/etc.)
as quote sources. Require ≥40 chars of non-path content on both sides.

**Touchpoints:** `src/ctx_rm/eval/trace/reference_graph.py` (rewrite
`_rule_exact_quote`, add `_originating_tool`, `_is_quote_source`,
`_is_quote_target`, `_has_quote_match`, initialize
`self._tool_use_by_id` and `self._ambient_tokens = set()` in
`_populate`; **also delete the dead `result_path` write in
`_rule_file_reread`** — Task 2's reviewer deferred it to this task).
Plus `tests/eval/trace/test_reference_graph.py` (add
`TestExactQuoteSourceGuard` with three tests from the plan).

**Non-goal:** do not populate `_ambient_tokens` here. Task 5 does
that. Task 4 just initializes it as an empty set so `_has_quote_match`
can reference it.

**Don't forget:** the positive test `TestExactQuoteEdge::test_later_text_quoting_tool_result`
must still pass. If your rewrite breaks it, the new rules are too
strict — stop and investigate before adjusting the spec.

**Sanity check after implementing:** on 5 tuning traces, record
exact_quote edge counts pre-Task-4 and post-Task-4. Counts should drop
meaningfully but not to zero. Put the numbers in the commit body.

### Task 5 — per-trace ambient-token index

**Goal:** drop any gating identifier token that appears in more than
25% of a trace's tool_results. This is the corpus-data-driven
replacement for a hardcoded SDK stoplist. Prevents generic boilerplate
like `SessionManager` from gating quote edges when it appears in every
tool_result.

**Touchpoints:** `_build_ambient_index` method on `ReferenceGraph`,
called from `_populate` before `_rule_exact_quote`. Constants
`_AMBIENT_MIN_RESULTS_FOR_INDEX = 4` and
`_AMBIENT_FREQUENCY_THRESHOLD = 0.25`. Exact code in the plan.

**Tests:** `TestAmbientTokenFilter` with two cases — ambient
`SessionManager` does not gate, distinctive
`authenticate_user_with_token_v42` still gates.

### Task 6 — `file_reread` requires concrete file path

**Goal:** kill the awoc-only FP mode where two Globs on `/awoc` with
different patterns produce a bogus reread edge because both have
`source_file=/awoc`.

**Touchpoints:** add `_is_concrete_file_path(path) -> bool` on
`ReferenceGraph` rejecting paths that contain glob metacharacters
(`*?[]{}`) or have no dotted leaf. Gate both loops in
`_rule_file_reread` on it. Tests in `TestFileRereadDirectoryGuard`.

### Task 7 — `file_discovery` edge kind

**Goal:** close the biggest FN hole in Phase A1. When an earlier
tool_result body lists a file path as a standalone token and a later
`tool_use` reads that exact path, emit an edge.

**Touchpoints:** add `FILE_DISCOVERY = "file_discovery"` to
`ReferenceEdgeKind`, add `_rule_file_discovery` on `ReferenceGraph`
(between `_rule_file_reread` and `_rule_exact_quote` in `_populate`),
add `_path_is_standalone(path, body) -> bool` helper using
`_DISCOVERY_BOUNDARY_RE`. One discovery edge per target is enough.
Tests in `TestFileDiscoveryEdge`.

### Task 8 — validation audit on held-out traces

**Goal:** prove the rewritten strict graph has precision ≥ 0.90 on
unseen traces.

**Touchpoints:**
- Add `--paths-file` and `--split` flags to
  `scripts/audit/phaseA1_reference_graph.py`.
- Run the sampler against `docs/eval/phaseB0_validation_split.json`,
  `--split tuning`, writing to
  `docs/eval/phaseB0_audit_tuning.jsonl`.
- **Dispatch a labeling subagent** with the same rubric used in
  Phase A1 (see `docs/eval/phaseA-findings.md`'s A1 section for the
  labeling protocol). Output to `docs/eval/phaseB0_tuning_labels.md`.
- If tuning precision is below 0.90, iterate on the rules from
  Tasks 4–7 (TDD, same pattern as before). Stop iterating once tuning
  is ≥ 0.90 OR you risk regressing existing unit tests.
- Run the sampler against `--split validation`, `--seed 2`, writing
  to `docs/eval/phaseB0_audit_validation.jsonl`. Dispatch the labeling
  subagent **exactly once** on the validation split.
- Write `docs/eval/phaseB-reference-graph.md` reporting old (0.602)
  vs. tuning vs. validation precision per-rule and overall.

**This is one of the two tasks where OPUS is worth spending on the
reviewer/analysis subagent.** Use sonnet for the labeling subagent
(it's pattern matching) and opus only when interpreting the final
validation result and deciding whether to ship or iterate.

### Task 9 — retention metric swap

**Goal:** replace `critical_segment_retention_k5` with
`critical_segment_retention` (horizon = `10**9` = all future) as the
headline metric, add `critical_segment_retention_k10` as a secondary
short-horizon column. Rationale in `docs/eval/phaseA-findings.md` A3.

**Touchpoints:** `src/ctx_rm/eval/l1_mechanism/metrics.py` (dataclass
fields, `compute_metrics`, `_critical_segment_retention` must use the
public `graph.earliest_future_turn(sid)` API added in Task 1),
`src/ctx_rm/eval/cli.py` (table column names), `tests/eval/l1_mechanism/test_runner.py`
(two existing assertions on `critical_segment_retention_k5` need
updating).

### Task 10 — `L1RunConfig.disable_bypass` flag

**Goal:** let the runner disable ContextBus admission bypass so L1
measures eviction alone, not admission + eviction. Required because
Phase A4 showed 59% of awoc tokens never enter Active at the default
threshold.

**Touchpoints:** add `disable_bypass: bool = False` to
`L1RunConfig`, plumb through `run_l1` by setting
`admission_threshold=sys.maxsize` on the `ContextBus` constructor
when `disable_bypass=True`. Test in `test_runner.py` with a crafted
trace containing a 2500-token tool_result.

### Task 11 — CLI dual-mode bypass output

**Goal:** `ctx-rm eval l1 --bypass-modes {on,off,both}` emits one
result table per bypass mode. "both" (default? your call — the plan
says yes) emits two tables per budget.

**Touchpoints:** `src/ctx_rm/eval/cli.py` run loop expanded to iterate
over bypass modes; table renderer keyed on
`(budget, policy, bypass)`. Smoke test on 10 traces with `--policies lru`.

### Task 12 — CLI default filter + budget grid

**Goal:** move the corpus filter and budget grid defaults into the
CLI so researchers don't have to remember the incantation.

**New defaults:** `--min-segments 40 --min-turns 8 --min-tool-use 8 --min-rereads 1 --budgets 4000,8000,16000,32000`.
Emit a "filter cascade" line in stdout so the chosen defaults are
visible in every run.

### Task 13 — full L1 rerun + baseline publication

**Goal:** publish `docs/eval/l1-postB0-baseline.md` — the new ground
truth against which Phase B policy work is measured.

**Commands:** `uv run ctx-rm eval l1 --project awoc --max-traces 200
--policies oracle,random,lru,clock,budget,arc,innodb --mode strict
--bypass-modes both --seed 0 --json results/b0_awoc_strict.json`, and
the same with `--mode lenient`. Commit both JSON result files.

**Analysis:** for each (budget, bypass, mode) combination, report
retention / retention@10 / eviction precision / eviction recall /
churn / tokens_evicted with 95% bootstrap CIs. Call out any ordering
changes vs. the pre-B0 baseline in `docs/eval/phaseA-findings.md` A5.

**Opus-worthy moment:** the interpretation of the baseline for the
paper. Dispatch an opus reviewer to read the baseline + the Phase A
findings and tell you what the story is before you write the summary.

### Task 14 — LRU = ARC = InnoDB investigation

**Goal:** understand why these three policies produce identical
eviction sequences on agent traces (confirmed to four decimals in
Phase A5). Decide between (a) publish the degeneracy as a paper
finding, (b) fix the signal to make ARC/InnoDB reactive, (c) drop
them from the main table.

**This is the other opus-worthy moment.** Dispatch opus for the
investigation write-up at `docs/eval/phaseB0-policy-identity.md`.
Haiku can do the initial exploration of `core/policies/arc.py` and
`core/policies/innodb.py` to gather facts; opus decides the paper
framing.

### Task 15 — frozen-trace L1 regression test

**Goal:** pick one small tuning trace (~60 segments), commit it
under `tests/eval/fixtures/frozen_trace.jsonl`, write a regression
test that locks in specific retention numbers for LRU and Oracle.
Any future metric regression breaks CI.

**Touchpoints:** `tests/eval/fixtures/frozen_trace.jsonl` (new),
`tests/eval/l1_mechanism/test_l1_regression.py` (new).

## Execution pattern (the token-conscious version)

**Do most work yourself.** Only spawn subagents when the task is
genuinely independent or the token volume would poison the main
conversation.

**Model selection:**
- **Haiku:** codebase exploration, grep-and-summarize, reading large
  files to extract a specific fact. Use for "where is X defined"
  and "list all call sites of Y".
- **Sonnet:** implementation. Every Task 4–12 implementer is sonnet.
  The plan is detailed enough that sonnet only needs to execute it.
- **Opus:** the two judgment moments — interpreting the Task 8
  validation result and framing the Task 14 policy-identity finding.
  That's it. Do NOT use opus for implementers, code review, or
  spec compliance checking.

**Review cadence:**
- For mechanical tasks (T9–T12, T15): self-review by reading the
  diff and running tests. Do not spawn a reviewer subagent.
- For rule-change tasks (T4–T7): run tests, run ruff, then inline
  the edge-count sanity check on 5 tuning traces before committing.
  A reviewer subagent is optional — run one (sonnet) if you feel
  uncertain, skip otherwise.
- For T8 and T14: opus reviewer on the final analysis, not on
  intermediate steps.

**Commit cadence:** one task, one commit. Commit message style:
`eval: <imperative>` matching the existing branch log.

**Do NOT:**
- Spawn a subagent for every file read.
- Spawn three subagents (implementer + spec + quality) per task.
  The superpowers pattern burned 94% of the prior session's tokens;
  we are explicitly walking away from it.
- Ask the user before every task. Proceed in plan order and only
  pause at Task 8 (after tuning audit, before validation audit) and
  Task 13 (before running the final L1 suite) and Task 14 (after
  the investigation, before deciding a/b/c).

## Finishing

When all 16 tasks are committed and green:

1. `uv run pytest -q` — all tests pass (expect ~180).
2. `uv run ruff check src/ tests/` — clean.
3. `git log --oneline main..phase-b0-hardening` — should be about
   20 commits. Squash nothing. The per-task history is the story.
4. Merge to main with a merge commit (`git merge --no-ff`) from a
   fresh checkout of main. Do not force-push.
5. Summarize the B0 outcome in one paragraph: new strict precision,
   new retention@all_future baseline numbers, any policy ordering
   changes, the LRU=ARC=InnoDB decision.

## Open questions to flag to the user during execution

- **Task 8 iteration stopping rule:** if tuning precision gets to
  0.87 and iterating further would require regressing a unit test,
  ship 0.87 and document it honestly. Do not chase 0.90 at the cost
  of correctness. Tell the user.
- **Task 14 decision:** (a)/(b)/(c) is a paper framing call. Draft
  your recommendation with the opus reviewer, then pause for the
  user to sign off before editing any policy code.
- **ctx-rm vs awoc corpus:** ctx-rm has only 5 eligible traces after
  the filter. Do not bootstrap CIs on it; use it only as a consistency
  check. Treat awoc as the primary corpus.

## That is the full remaining Phase B0 scope. Start at Task 4.
