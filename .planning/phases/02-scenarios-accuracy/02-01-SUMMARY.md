---
phase: 02-scenarios-accuracy
plan: 01
subsystem: benchmarks
tags: [fixtures, yaml, benchmark-tasks, scale-testing]

requires:
  - phase: 01-agent-hardening
    provides: "AgentLoop with tools, done-tool termination, structlog"
provides:
  - "SCALE-001 fixture: 10-file web service with cross-file auth bug (37K tokens)"
  - "SCALE-002 fixture: 12-file data processing project for rename refactoring (30K tokens)"
  - "SCALE-003 fixture: 12 report files with buried critical facts for synthesis (39K tokens)"
  - "3 SCALE task YAML definitions with evaluators in benchmark_tasks.yaml"
affects: [02-scenarios-accuracy, 03-experiment-proof, 04-budget-calibration]

tech-stack:
  added: []
  patterns: ["heavyweight fixtures with realistic noise padding", "multi-file evaluation checks"]

key-files:
  created:
    - benchmarks/fixtures/scale_codebase_nav/
    - benchmarks/fixtures/scale_multi_refactor/
    - benchmarks/fixtures/scale_info_synthesis/
  modified:
    - docs/context_removal_benchmark_tasks.yaml

key-decisions:
  - "Fixture token counts target 20K/30K/40K via realistic code/prose padding, not filler"
  - "SCALE-001 bug is validate_token vs verify_token with settings.py needle"
  - "SCALE-002 includes hidden method rename requirement in MIGRATION.md"
  - "SCALE-003 uses 10 buried numerical facts across 10 department reports"

patterns-established:
  - "Scale fixtures use realistic business/technical content for noise, not lorem ipsum"
  - "Each SCALE task has context_injections totaling 17K-35K additional noise tokens during runs"

duration: 34min
completed: 2026-02-08
---

# Phase 2 Plan 1: Heavyweight Scale Fixtures Summary

**Three SCALE benchmark fixtures (20K/30K/40K tokens) with realistic Python projects and business reports that force meaningful eviction pressure**

## Performance

- **Duration:** 34 min
- **Started:** 2026-02-08T15:12:53Z
- **Completed:** 2026-02-08T15:46:44Z
- **Tasks:** 2
- **Files created:** 34

## Accomplishments
- Created SCALE-001: 10-file web service (149K chars) with auth.py bug calling validate_token instead of verify_token; settings.py contains the needle TOKEN_VERIFY_METHOD = "verify_token"
- Created SCALE-002: 12-file data processing project (116K+ chars) with DataProcessor class to rename to StreamProcessor; MIGRATION.md contains hidden process_batch -> stream_batch requirement
- Created SCALE-003: 10 detailed business reports (155K chars) each containing one buried numerical fact, plus template and empty output file
- Added all three SCALE tasks to benchmark YAML with well-formed evaluation checks; total task count now 16

## Task Commits

Each task was committed atomically:

1. **Task 1: Create SCALE-001/002/003 fixture directories** - `f3df660` (feat)
2. **Task 2: Add SCALE task YAML definitions with evaluators** - `d2affe4` (feat)

## Files Created/Modified
- `benchmarks/fixtures/scale_codebase_nav/` - 10 Python files forming a web service with cross-file bug
- `benchmarks/fixtures/scale_multi_refactor/` - 12 files (8 Python + MIGRATION.md + docs + README + tests) for rename refactoring
- `benchmarks/fixtures/scale_info_synthesis/` - 10 reports + template + empty output for info synthesis
- `docs/context_removal_benchmark_tasks.yaml` - Added SCALE-001, SCALE-002, SCALE-003 task definitions

## Decisions Made
- Used realistic business/technical prose for noise padding rather than cycling filler text
- SCALE-001 auth bug placed in verify_request_token method at line ~45 of auth.py with clear comment marking it
- SCALE-002 needle placed in MIGRATION.md rather than inline code comments to test agent's ability to find critical migration notes
- SCALE-003 facts are naturally embedded in report prose (e.g., "$4.2M" in Q1 revenue section) rather than highlighted

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Initial SCALE-003 report files were only ~98K chars total; required multiple rounds of expanding appendix sections to reach the ~155K target near 40K tokens

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All three fixture directories exist and are loadable via FixtureManager
- TaskLoader successfully loads all 16 tasks including the 3 new SCALE entries
- Evaluation checks reference files that exist in the fixture directories
- Ready for Phase 2 Plan 2 (scenario runner) and Plan 3 (experiment integration)

## Self-Check: PASSED

- All 9 key files: FOUND
- Commits f3df660, d2affe4: FOUND
- SCALE-001: 10 Python files
- SCALE-002: 12 files total
- SCALE-003: 12 txt files
- Total YAML tasks: 16

---
*Phase: 02-scenarios-accuracy*
*Completed: 2026-02-08*
