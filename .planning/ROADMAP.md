# Roadmap: ctx-rm

## Milestones

- v1.0 Evidence Infrastructure - Phases 1-4 (shipped 2026-02-08)
- v1.1 Experimental Validation - Phases 5-6 (in progress)

## Phases

<details>
<summary>v1.0 Evidence Infrastructure (Phases 1-4) - SHIPPED 2026-02-08</summary>

### Phase 1: Agent Hardening
**Goal**: Agent can reliably complete multi-step tasks without hallucination or tool misuse
**Plans**: 2 plans

Plans:
- [x] 01-01: Done tool and tool output improvements
- [x] 01-02: System prompt, failure hints, turn logging

### Phase 2: Scenarios and Accuracy
**Goal**: Heavyweight benchmark scenarios that force real eviction pressure, with calibrated budgets
**Plans**: 3 plans

Plans:
- [x] 02-01: SCALE scenarios (20K/30K/40K tokens)
- [x] 02-02: Budget calibration and admission tuning
- [x] 02-03: Content-based recall with precision tracking

### Phase 3: Experiment Framework
**Goal**: Automated multi-config experiment runner with YAML configs and output formats
**Plans**: 1 plan

Plans:
- [x] 03-01: Experiment CLI, YAML config, Rich tables, CSV export

### Phase 4: Evidence Tooling
**Goal**: Analysis functions and CLI that evaluate experiment results against EVID criteria
**Plans**: 2 plans

Plans:
- [x] 04-01: Evidence analyzer functions (6 analysis types)
- [x] 04-02: `ctx-rm analyze` CLI with Rich evidence tables

</details>

### v1.1 Experimental Validation (In Progress)

**Milestone Goal:** Run all experiments against llama-server, analyze results, and produce a findings report that proves (or disproves) the ctx-rm thesis with reproducible data.

#### Phase 5: Experiment Runs
**Goal**: All 5 experiment suites complete with CSV results in results/experiments/
**Depends on**: Phase 4
**Requirements**: RUN-01, RUN-02, RUN-03, RUN-04, RUN-05
**Success Criteria** (what must be TRUE):
  1. `results/experiments/eviction-accuracy/` contains 3-run CSV data for BudgetAware vs LRU across SCALE-001/002/003
  2. `results/experiments/recall-effectiveness-on/` and `recall-effectiveness-off/` contain 3-run CSV data for recall on vs off on SCALE-003
  3. `results/experiments/budget-sensitivity/` contains 3-run CSV data for 9 budget levels (500-100K) on SPEC-001
  4. `results/experiments/noise-degradation/` contains 5-run CSV data for 7 tasks in full vs ctx-rm mode
  5. `results/experiments/context-window-scaling/` contains 3-run CSV data for 4 budget levels across SCALE tasks
**Plans**: 2 plans

Plans:
- [ ] 05-01-PLAN.md -- Run eviction accuracy and recall effectiveness experiments (30 combos: RUN-01, RUN-02)
- [ ] 05-02-PLAN.md -- Run budget sensitivity, noise degradation, and context window scaling experiments (145 combos: RUN-03, RUN-04, RUN-05)

#### Phase 6: Analysis and Findings
**Goal**: All experiment data analyzed, EVID criteria evaluated, and FINDINGS.md produced with thesis verdict
**Depends on**: Phase 5
**Requirements**: RPT-01, RPT-02, RPT-03
**Success Criteria** (what must be TRUE):
  1. `ctx-rm analyze` has been run on every results directory and produces per-EVID verdicts
  2. FINDINGS.md exists with data tables, pass/fail verdict for each of 5 EVID criteria, and overall thesis conclusion
  3. At least 3 of 5 EVID criteria show PASS with supporting numerical evidence
**Plans**: TBD

Plans:
- [ ] 06-01: Analyze all experiment results and produce FINDINGS.md

## Progress

**Execution Order:** 5 -> 6

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Agent Hardening | v1.0 | 2/2 | Complete | 2026-02-08 |
| 2. Scenarios and Accuracy | v1.0 | 3/3 | Complete | 2026-02-08 |
| 3. Experiment Framework | v1.0 | 1/1 | Complete | 2026-02-08 |
| 4. Evidence Tooling | v1.0 | 2/2 | Complete | 2026-02-08 |
| 5. Experiment Runs | v1.1 | 0/2 | Not started | - |
| 6. Analysis and Findings | v1.1 | 0/1 | Not started | - |
