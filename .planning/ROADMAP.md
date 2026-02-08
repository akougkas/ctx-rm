# Roadmap: ctx-rm

## Overview

Transform ctx-rm from a single-datapoint proof of concept into a statistically validated system by hardening the agent, building heavyweight scenarios that force eviction at scale, automating experiment runs, and producing reproducible evidence that eviction + recall beats naive context management.

## Phases

- [x] **Phase 1: Agent Hardening** - Make the agent competent enough to prove the thesis
- [ ] **Phase 2: Scenarios & Accuracy** - Heavyweight scenarios, scoring/recall improvements, budget calibration
- [ ] **Phase 3: Experiment Framework** - Automated multi-config comparison runs with structured output
- [ ] **Phase 4: Evidence** - Run experiments and produce the proof data

## Phase Details

### Phase 1: Agent Hardening
**Goal**: Agent can solve multi-step coding tasks using tools effectively, terminate cleanly, and recover from errors
**Depends on**: Nothing (first phase)
**Requirements**: TOOL-01, TOOL-02, TOOL-03, TOOL-04, LOOP-01, LOOP-02, LOOP-03, LOOP-04
**Success Criteria** (what must be TRUE):
  1. Agent calls `done` tool with structured result when task is complete, and the loop terminates cleanly
  2. Agent reads partial files (line ranges) and uses grep with filters/limits instead of dumping entire files into context
  3. System prompt guides agent through read-before-write workflow and change verification without mentioning context management
  4. After 3+ consecutive failed tool calls, loop injects a hint and agent recovers
  5. Each turn's tool call, outcome, and token count are logged and visible in post-run output
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md -- Tool upgrades (done tool, file_read line ranges, grep_search filters, run_shell exit codes)
- [x] 01-02-PLAN.md -- Loop improvements (done handling, system prompt, turn logging, failure hints)

### Phase 2: Scenarios & Accuracy
**Goal**: Heavyweight scenarios exist that force real eviction pressure, and scoring/recall improvements keep the right information active
**Depends on**: Phase 1
**Requirements**: SCEN-01, SCEN-02, SCEN-03, SCEN-04, SCORE-01, RECALL-01, RECALL-02, RECALL-03, ADM-01
**Success Criteria** (what must be TRUE):
  1. SCALE-001/002/003 scenarios run end-to-end with 20K/30K/40K+ token context pressure respectively
  2. Budget calibration produces >3 eviction cycles per ctx-rm run on every task
  3. HeuristicScorer uses configurable per-source weights (needle:0.9 evicts last, noise:0.1 evicts first)
  4. Previously-evicted file content is recalled automatically when agent re-reads that file, bounded by a per-turn recall budget
  5. Recall precision is tracked and reported (% of recalls that appeared in subsequent tool calls)
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md -- Heavyweight scenarios (SCALE-001/002/003 fixture creation, task YAML, evaluators) [wave 1]
- [x] 02-02-PLAN.md -- Scoring and recall improvements (per-source weights, content-based recall, recall budget, precision tracking) [wave 1]
- [x] 02-03-PLAN.md -- Budget calibration and admission tuning (calibrate all tasks, tune admission threshold from profiled file sizes) [wave 2, depends on 02-01]

### Phase 3: Experiment Framework
**Goal**: A single CLI command runs all experiment combinations and produces structured comparison output
**Depends on**: Phase 2
**Requirements**: EXPR-01, EXPR-02, EXPR-03
**Success Criteria** (what must be TRUE):
  1. `ctx-rm experiment` accepts a YAML config specifying tasks, modes, policies, budgets, and N runs
  2. Per-config output includes median tokens, pass rate, eviction count, and recall count
  3. Results are displayed as a Rich comparison table and exported as CSV
**Plans**: 1 plan

Plans:
- [ ] 03-01-PLAN.md -- Experiment config model, combination runner, aggregation, Rich table, CSV export

### Phase 4: Evidence
**Goal**: Reproducible data proves that ctx-rm eviction + recall outperforms naive context management on heavyweight workloads
**Depends on**: Phase 3
**Requirements**: EVID-01, EVID-02, EVID-03, EVID-04, EVID-05
**Success Criteria** (what must be TRUE):
  1. Eviction accuracy data shows BudgetAware evicts >80% noise segments before any needle, compared against LRU baseline
  2. SCALE-003 pass rate with recall enabled is measurably higher than with recall disabled
  3. Budget sweep on SPEC-001 (1K-100K) identifies the knee where ctx-rm matches full mode at minimal token cost
  4. At least one task demonstrably FAILS with full context (noise degrades model) but PASSES with ctx-rm
  5. Context window scaling data (4K/8K/16K/32K) shows ctx-rm maintains quality where full mode degrades
**Plans**: 2 plans

Plans:
- [ ] 04-01: Run core experiments (eviction accuracy, recall effectiveness, budget sensitivity)
- [ ] 04-02: Scaling and edge cases (context window scaling, identify the full-fails-ctxrm-passes task)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Agent Hardening | 2/2 | ✓ Complete | 2026-02-08 |
| 2. Scenarios & Accuracy | 3/3 | ✓ Complete | 2026-02-08 |
| 3. Experiment Framework | 0/1 | Not started | - |
| 4. Evidence | 0/2 | Not started | - |
