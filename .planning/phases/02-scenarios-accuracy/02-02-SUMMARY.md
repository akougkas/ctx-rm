---
phase: 02-scenarios-accuracy
plan: 02
subsystem: agents, scoring
tags: [recall, content-recall, budget, precision, scorer, source-weights]

requires:
  - phase: 01-agent-hardening
    provides: "AgentLoop with task-based recall, HeuristicScorer with source_scores"
provides:
  - "Content-based recall on file_read tool results"
  - "Per-turn recall budget limiting (recall_budget param)"
  - "Recall precision tracking (hits/total in AgentResult)"
  - "Validated configurable source weights in HeuristicScorer"
affects: [02-scenarios-accuracy, 03-budget-calibration]

tech-stack:
  added: []
  patterns: ["content-based recall alongside task-based recall", "per-turn budget counters with reset on advance_turn", "precision tracking via content overlap detection"]

key-files:
  created:
    - tests/core/test_scorer_recall.py
  modified:
    - src/ctx_rm/agents/loop.py

key-decisions:
  - "Content recall searches by file path + result snippet, not just task text"
  - "Content recall allows recalling tool segments (unlike task-based recall which only recalls safe sources)"
  - "Recall precision uses first 100 chars of recalled content as overlap check"
  - "recall_budget default is 3 per turn"

patterns-established:
  - "_try_content_recall fires after each tool result, separate from _try_recall at turn start"
  - "_recalls_this_turn counter resets at bus.advance_turn boundary"
  - "recall_precision is hits/total float on AgentResult (0.0 when no recalls)"

duration: 3min
completed: 2026-02-08
---

# Phase 02 Plan 02: Scorer Weights and Content Recall Summary

**Content-based recall on file_read, per-turn recall budget, and recall precision tracking with configurable source weights validation**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-08T15:13:54Z
- **Completed:** 2026-02-08T15:17:16Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Validated HeuristicScorer already supports configurable per-source weights (SCORE-01 confirmed)
- Implemented content-based recall that fires on file_read tool results, searching evicted segments by path and content overlap (RECALL-01)
- Added per-turn recall budget (default 3) with counter reset on turn boundary (RECALL-02)
- Added recall precision tracking: measures what fraction of recalls proved useful in subsequent tool calls (RECALL-03)
- 137 total tests pass (9 new + 128 existing, zero regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing tests** - `dcacee9` (test)
2. **Task 2: Implement features** - `3fe06d5` (feat)

## Files Created/Modified
- `tests/core/test_scorer_recall.py` - 9 tests covering SCORE-01, RECALL-01, RECALL-02, RECALL-03
- `src/ctx_rm/agents/loop.py` - Content recall, budget, precision tracking, recall_precision on AgentResult

## Decisions Made
- Content recall searches by file path + result snippet (not just task text) for higher relevance
- Content recall allows recalling tool segments (broadened from task-based recall's safe-source filter)
- Precision tracking uses 100-char content overlap as hit detection
- Default recall_budget=3 per turn; 0 disables recall entirely

## Deviations from Plan

None - plan executed exactly as written. SCORE-01 (configurable source weights) was confirmed already implemented; tests validated the existing behavior.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All recall features complete: task-based + content-based with budget and precision tracking
- Ready for scenario benchmarks that test recall effectiveness under budget pressure
- recall_precision metric available for experiment harness to measure recall quality

---
*Phase: 02-scenarios-accuracy*
*Completed: 2026-02-08*
