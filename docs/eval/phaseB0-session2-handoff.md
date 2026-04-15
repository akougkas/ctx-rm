# Phase B0 handoff — session 2, resuming at T12

Copy everything below the `---` into the first message of a new Claude
Code session opened on this project. The cumulative B0 work so far
sits on branch `phase-b0-hardening` in worktree
`/home/akougkas/projects/ctx-rm/.worktrees/phase-b0-hardening`.

---

You are resuming Phase B0 of ctx-rm. Tasks 0–11 are committed.
Tasks 12–15 remain. Work from
`/home/akougkas/projects/ctx-rm/.worktrees/phase-b0-hardening` on
branch `phase-b0-hardening`. Use `uv run ...` for everything.

## Baseline at session start

- **179 tests passing**, ruff clean on `src/ctx_rm/eval/` and
  `tests/eval/`.
- `git log --oneline main..HEAD` should show ~12 B0 commits ending in
  `8068bea eval: CLI --bypass-modes emits one table per bypass setting`.

## Read these first, in this order

1. `docs/eval/phaseB0-handoff.md` — the original session-1 handoff.
   It defines the three hard rules ("no cheating", "apples to
   apples", "optimize codebase not benchmark"), the overfitting
   guardrail, the model-selection policy (haiku/sonnet/opus), and the
   pause points. These still apply.
2. `docs/eval/phaseB0-hardening-plan.md` — canonical task spec.
   T12–T15 start at line 1509. Treat the code snippets as literal.
3. `docs/eval/phaseB-reference-graph.md` — what shipped from T8. You
   need to know: file_reread and file_discovery pass the 0.90 bar on
   both splits; exact_quote does not (0.700 tuning → 0.236 validation,
   a 17.6 pp gap). We chose NOT to iterate the rules further because
   the B0 discipline forbids re-tuning after opening the validation
   split. The fix candidate — "require the 20-char verbatim run to
   contain the gating identifier token" — is documented in that doc
   and is for Phase C. Do not apply it here.
4. `CLAUDE.md` — coding conventions. Key reminders:
   `from __future__ import annotations`, `X | Y` unions, no
   `[noun] - [clause]` sentences in prose, docstrings in Google style,
   ruff E,F,I,N,W,UP,B,SIM,RUF at line-length 100.

## Commit log so far on this branch (session 1)

```
8068bea eval: CLI --bypass-modes emits one table per bypass setting
bcc58ed eval: L1RunConfig.disable_bypass plumbs to ContextBus admission
f6ba2da eval: headline retention is all-future; add retention@10 secondary
8fc4799 eval: reference graph validation audit — 0.71 pooled, mixed by rule
eeb8cb7 eval: add file_discovery edge kind for listing-based references
c3c2878 eval: require concrete file path for file_reread edges
feac490 eval: ambient-token filter for exact_quote gating
ea19179 eval: tighten exact_quote rule — strip paths, reject listing sources
2e66faa eval: path-token boundary set + docstring fix
57cdef7 eval: add _path_tokens helper for quote-rule hardening
c6d8fa9 eval: refactor ReferenceGraph._populate into per-rule methods
cc49721 eval: add ReferenceGraph.earliest_future_turn public API
```

Session-1 tuning vs validation precision (locked, do not re-run):

| rule            | tuning | validation | target |
| --------------- | -----: | ---------: | -----: |
| file_reread     |  1.000 |      1.000 |   0.90 |
| file_discovery  |  1.000 |      0.951 |   0.90 |
| exact_quote     |  0.700 |      0.236 |   0.90 |
| overall         |  0.886 |      0.710 |   0.90 |

## Execution pattern (same as session 1)

- Do most work yourself. Only spawn subagents for T13's opus baseline
  interpretation and T14's opus investigation writeup. Those are the
  two opus-worthy moments left.
- Sonnet-tier subagents are fine for T14's initial fact-gathering on
  `core/policies/arc.py` and `core/policies/innodb.py`. Opus decides
  the paper framing after they report.
- One task, one commit. Commit message style:
  `eval: <imperative>`. Do not squash.
- Pause points remaining: **T13 (before running the final L1 suite)**
  and **T14 (after the investigation, before deciding a/b/c)**. Ask
  the user. Everything else: proceed.

## Remaining tasks

Each task's full spec is in `docs/eval/phaseB0-hardening-plan.md`.
This list is a navigation aid.

### Task 12 — CLI default filter + budget grid

Plan reference: plan line 1509.

- Change CLI defaults in `src/ctx_rm/eval/cli.py` `cmd_l1`:
  - `--min-segments` default 10 → 40
  - add `--min-turns` default 8
  - add `--min-tool-use` default 8
  - add `--min-rereads` default 1
  - `--budgets` default `8000,32000,128000` → `4000,8000,16000,32000`
- Apply the filter cascade inside the trace-loading loop. The filter
  check is in the plan under T12 Step 2. Don't try to share it with
  the audit script's filter; keep it local to the CLI.
- Emit a "filter cascade" line so the run log shows which filters
  fired and how many traces survived.
- Smoke test: `uv run ctx-rm eval l1 --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc --project awoc --max-traces 20 --policies oracle,lru --bypass-modes off`.
- Commit: `eval: CLI defaults — corpus filter and budget grid from Phase A`.

### Task 13 — full L1 rerun + baseline publication (PAUSE FIRST)

Plan reference: plan line 1575. **Pause for user sign-off before
running the commands** — these runs are expensive and produce the
numbers the Phase B policy work will be measured against.

Commands when green-lit:

```
uv run ctx-rm eval l1 \
    --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \
    --project awoc --max-traces 200 \
    --policies oracle,random,lru,clock,budget,arc,innodb \
    --mode strict --bypass-modes both --seed 0 \
    --json results/b0_awoc_strict.json
```

And the same with `--mode lenient --json results/b0_awoc_lenient.json`.

Commit both JSON files plus `docs/eval/l1-postB0-baseline.md`. The
doc is a writeup, not a template. For every (budget, bypass, mode)
combination, report retention / retention@10 / eviction precision /
eviction recall / churn / tokens_evicted with their 95% bootstrap
CIs, and call out any policy ordering changes vs. pre-B0 numbers in
`docs/eval/phaseA-findings.md` A5.

**Opus moment.** After the runs, dispatch an opus reviewer to read
the baseline JSON plus phaseA-findings.md A5 and tell you the story
before you write the summary section. Prompt it with: "What changed
vs. the pre-B0 numbers, and is the story 'ctx-rm policies are
indistinguishable from LRU on agent traces' or 'ctx-rm reveals that
baseline eviction policies are structurally identical on agent
workloads'?" The difference is the framing we ship to the paper.

Commit: `eval: publish L1 post-B0 baseline (awoc strict + lenient)`.

### Task 14 — LRU = ARC = InnoDB investigation (PAUSE FIRST)

Plan reference: plan line 1620. **Pause for user sign-off between
the investigation and the a/b/c decision.**

Goal: understand why these three policies produce identical eviction
sequences on agent traces (Phase A5 confirmed to four decimals).
Options:
  - (a) publish the degeneracy as a paper finding,
  - (b) fix the signal so ARC/InnoDB become reactive,
  - (c) drop them from the main table.

Haiku for the initial fact-gathering on `src/ctx_rm/core/policies/arc.py`
and `src/ctx_rm/core/policies/innodb.py`. Collect: which signals the
policies consume (recency_beads? hot_queue? scorer?), how eviction
choices are derived, what inputs would need to differ for them to
diverge. Pass that report to an **opus** writeup agent for the
framing call.

Opus writes `docs/eval/phaseB0-policy-identity.md`. Then pause for
the user to pick a/b/c. Do not touch policy code before sign-off.

Commit (after user pick): `eval: policy identity investigation — <finding>`.

### Task 15 — frozen-trace L1 regression test

Plan reference: plan line 1700.

- Pick one small tuning trace (~60 segments). Do not pick from the
  16 burned traces in `docs/eval/phaseB0-burn-traces.txt` and do not
  pick from the validation split. The tuning split in
  `docs/eval/phaseB0_validation_split.json` is the right pool.
- Commit it verbatim under `tests/eval/fixtures/frozen_trace.jsonl`.
- `tests/eval/l1_mechanism/test_l1_regression.py` (new file) runs
  LRU and Oracle on the frozen trace at one budget and asserts
  specific retention numbers with `== pytest.approx(X, abs=1e-6)`.
  Exact numbers are whatever the current code produces — get them
  once, hard-code them, document that any diff means a metric change.
- Test must run under `uv run pytest -q`. Commit:
  `eval: frozen-trace L1 regression fixture + test`.

## Finishing

When all 16 tasks are committed and green:

1. `uv run pytest -q` — all tests pass (~181 expected).
2. `uv run ruff check src/ctx_rm/eval/ tests/eval/` — clean.
3. `git log --oneline main..phase-b0-hardening` — ~20 commits.
4. Write the B0 outcome paragraph: new strict precision, new
   retention@all_future baseline numbers, any policy ordering
   changes, the a/b/c decision. Paste it to the user.
5. Do NOT merge to main unless the user explicitly asks. Just report
   that the branch is ready.

## Open questions flagged from session 1

- **exact_quote precision ships at 0.236 on validation.** Documented
  in `docs/eval/phaseB-reference-graph.md`. The Phase C followup is
  the "gating-identifier-in-verbatim-window" fix. Do not apply it in
  B0 — it would contaminate the validation numbers.
- **T13 baseline interpretation is the biggest unknown.** The
  retention metric changed in T9 (now all-future horizon, not k=5);
  the admission bypass is now a dial in T10–T11; the reference graph
  rules moved in T4–T7. All the pre-B0 baseline numbers are now
  stale. The opus reviewer on T13 is there to tell you whether the
  new numbers tell the same paper story or a different one.
- **T14 a/b/c decision affects policy code.** If the user picks (b),
  you're in a real implementation task on ARC/InnoDB that could
  cascade into rerunning T13. Budget accordingly.

## That is the full remaining B0 scope. Start at Task 12.
