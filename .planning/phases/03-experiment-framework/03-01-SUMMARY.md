---
phase: 03-experiment-framework
plan: 01
subsystem: benchmarks
tags: [experiment, yaml, pydantic, rich, csv, aggregation, cli]

requires:
  - phase: 02-scenarios-accuracy
    provides: BenchmarkRunner, BUDGET_MAP, evaluator, task loader
provides:
  - ExperimentConfig Pydantic model with YAML parsing
  - generate_combinations with mode-aware dedup
  - ExperimentRunner with run_all and aggregate
  - AggregatedResult dataclass with median/pass_rate stats
  - write_csv export utility
  - ctx-rm experiment CLI command with --dry-run
affects: [04-results-analysis]

tech-stack:
  added: [csv]
  patterns: [yaml-driven experiment config, cartesian combination generation with mode dedup]

key-files:
  created:
    - src/ctx_rm/benchmarks/experiment.py
    - tests/benchmarks/test_experiment.py
  modified:
    - src/ctx_rm/cli/main.py

key-decisions:
  - "Non-ctx-rm modes deduplicated: policy/budget variations only apply to ctx-rm mode"
  - "budget=0 signals auto-select from BUDGET_MAP at runtime"
  - "Aggregation excludes errored runs from stats but counts them in num_errors"

patterns-established:
  - "ExperimentConfig.from_yaml classmethod pattern for YAML-to-Pydantic parsing"
  - "RunConfig/RunResult/AggregatedResult dataclass hierarchy for experiment data flow"

duration: 3min
completed: 2026-02-08
---

# Phase 3 Plan 1: Experiment Framework Summary

**YAML-driven experiment runner with cartesian combination generation, aggregation (median tokens, pass rate, eviction/recall counts), Rich table display, and CSV export via `ctx-rm experiment` CLI**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-08T17:38:43Z
- **Completed:** 2026-02-08T17:41:58Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- ExperimentConfig Pydantic model parses YAML with defaults, generate_combinations produces correct cartesian product with mode-aware dedup
- ExperimentRunner.aggregate computes median prompt tokens, pass rate, median eviction/recall counts across runs
- `ctx-rm experiment config.yaml` CLI command with Rich color-coded table, CSV export, and --dry-run flag
- 10 tests covering config parsing, combination generation, aggregation, CSV export, and dry-run

## Task Commits

Each task was committed atomically:

1. **Task 1: Experiment config model, combination runner, and aggregation** - `696f08a` (feat)
2. **Task 2: CLI experiment command with Rich table and CSV export** - `10a1286` (feat)

## Files Created/Modified
- `src/ctx_rm/benchmarks/experiment.py` - ExperimentConfig, RunConfig, RunResult, AggregatedResult, ExperimentRunner, generate_combinations, write_csv
- `src/ctx_rm/cli/main.py` - experiment command with Rich table rendering and CSV export
- `tests/benchmarks/test_experiment.py` - 10 tests for config, combinations, aggregation, CSV, dry-run

## Decisions Made
- Non-ctx-rm modes (full, minimal) are deduplicated: policy and budget variations only expand for ctx-rm mode
- budget=0 in RunConfig signals auto-select from BUDGET_MAP at runtime in ExperimentRunner.run_all
- Aggregation groups by (task_id, mode, policy, budget) and excludes errored runs from median/rate calculations

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Experiment framework complete, ready for multi-run experiments
- Full test suite: 159 tests passing (10 new + 149 existing)
- Phase 3 complete (single plan phase)

## Self-Check: PASSED

- FOUND: src/ctx_rm/benchmarks/experiment.py
- FOUND: tests/benchmarks/test_experiment.py
- FOUND: src/ctx_rm/cli/main.py
- FOUND: commit 696f08a
- FOUND: commit 10a1286

---
*Phase: 03-experiment-framework*
*Completed: 2026-02-08*
