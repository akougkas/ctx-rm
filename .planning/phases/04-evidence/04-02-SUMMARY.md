---
phase: "04-evidence"
plan: "02"
subsystem: "benchmarks, cli, experiments"
tags: [evidence, scaling, noise-degradation, analyzer, cli, rich-tables]
dependency_graph:
  requires: ["04-01"]
  provides: ["scaling-analysis", "noise-degradation-analysis", "analyze-cli", "evid-04-config", "evid-05-config"]
  affects: []
tech_stack:
  added: []
  patterns: ["Rich CLI evidence tables with color-coded thresholds", "graceful missing-data handling in CLI"]
key_files:
  created:
    - docs/experiments/context_window_scaling.yaml
    - docs/experiments/noise_degradation.yaml
  modified:
    - src/ctx_rm/benchmarks/analyzer.py
    - src/ctx_rm/cli/main.py
    - tests/benchmarks/test_analyzer.py
decisions:
  - "Budget proxies for effective context window size in scaling experiments"
  - "Noise degradation uses 5 runs for statistical confidence"
patterns-established:
  - "CLI analyze command dispatches to analyzer functions by analysis type string"
  - "Graceful skip pattern: missing data prints dim message instead of crashing"
metrics:
  duration: "4 min"
  completed: "2026-02-08"
---

# Phase 4 Plan 2: Evidence Collection and Report Summary

**Context window scaling (EVID-05) and noise degradation (EVID-04) experiment configs, extended analyzer with scaling/noise functions, and `ctx-rm analyze` CLI command with Rich evidence tables for all 5 analysis types.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-08
- **Completed:** 2026-02-08
- **Tasks:** 3 (2 auto + 1 checkpoint)
- **Files modified:** 5

## Accomplishments
- Context window scaling YAML config exercising 4K/8K/16K/32K budget levels across SCALE tasks
- Noise degradation YAML config targeting 7 tasks with 5 runs for statistical confidence on full-fails-ctxrm-passes hypothesis
- Analyzer extended with `compute_scaling_quality` and `find_noise_degradation` returning typed dataclasses
- `ctx-rm analyze` CLI command with Rich tables for eviction, recall, budget, scaling, and noise analysis types
- Graceful handling of missing result directories (no crash, dim skip message)

## Task Commits

Each task was committed atomically:

1. **Task 1: Context window scaling and noise degradation configs + analyzer extensions** - `048bc22` (feat)
2. **Task 2: Add ctx-rm analyze CLI command for Rich evidence display** - `ac41d67` (feat)
3. **Task 3: Checkpoint human-verify** - approved (no commit, verification only)

## Files Created/Modified
- `docs/experiments/context_window_scaling.yaml` - EVID-05 config: 4K/8K/16K/32K budgets on SCALE tasks
- `docs/experiments/noise_degradation.yaml` - EVID-04 config: 7 noisy tasks, 5 runs, ctx-rm vs full
- `src/ctx_rm/benchmarks/analyzer.py` - Added compute_scaling_quality, find_noise_degradation, ScalingRow, NoiseDegradationRow
- `src/ctx_rm/cli/main.py` - Added analyze command with Rich tables for 5 analysis types
- `tests/benchmarks/test_analyzer.py` - 3 new tests (scaling quality, noise degradation candidate/no-candidate)

## Decisions Made
- Budget used as proxy for effective context window size (model's physical window is fixed, budget constrains ctx-rm)
- Noise degradation uses 5 runs (vs 3 for other experiments) for higher statistical confidence on the degradation hypothesis

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All 6 experiment YAML configs exist and parse correctly
- Analyzer has 5 analysis functions covering all evidence types (EVID-01 through EVID-05)
- CLI has both `experiment` and `analyze` commands for end-to-end workflow
- Phase 04-evidence is complete; all evidence infrastructure is ready
- To generate actual evidence: run experiments with llama-server on mini:8080

---
*Phase: 04-evidence*
*Completed: 2026-02-08*
