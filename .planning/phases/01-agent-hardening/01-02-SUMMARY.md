---
phase: 01-agent-hardening
plan: 02
subsystem: agents
tags: [agent-loop, done-tool, structlog, failure-hints, system-prompt]

requires:
  - phase: 01-agent-hardening/01
    provides: "done tool in tools.py returning structured JSON via orjson"
provides:
  - "Agent loop with done-tool termination"
  - "Per-turn structlog logging (tool, outcome, tokens)"
  - "Failure hint injection after consecutive errors"
  - "Comprehensive system prompt for benchmark runner"
affects: [02-benchmark-suite, 03-budget-calibration]

tech-stack:
  added: []
  patterns: [done-tool detection in loop, failure tracking with threshold reset, user-hint injection]

key-files:
  created: []
  modified:
    - src/ctx_rm/agents/loop.py
    - src/ctx_rm/benchmarks/runner.py
    - tests/agents/test_loop.py

key-decisions:
  - "Done tool coexists with other tools in same turn: all execute, then loop stops"
  - "Failure hint injected as user-role message (not system) for OpenAI format compat"
  - "Failure counter resets after hint injection to avoid repeated hints"
  - "System prompt teaches tool usage patterns without mentioning context management"

patterns-established:
  - "Done-tool detection: tc.name == 'done' flag in tool processing loop"
  - "Failure tracking: _consecutive_failures counter with threshold and reset"
  - "_ingest_user_hint: user-role hint injection with source='system_hint'"

duration: 4min
completed: 2026-02-08
---

# Phase 1 Plan 2: Loop Improvements Summary

**Done-tool termination, per-turn structlog logging, failure hints after 3 consecutive errors, and comprehensive system prompt**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-08T14:41:46Z
- **Completed:** 2026-02-08T14:46:34Z
- **Tasks:** 4
- **Files modified:** 3

## Accomplishments
- Agent loop terminates cleanly on done tool call with structured JSON result in final_response
- Done tool coexists with other tool calls in same turn (all execute, then loop stops)
- Each tool call logged via structlog with tool name, 200-char outcome preview, prompt/completion tokens
- After 3 consecutive failed tool calls, hint message injected guiding agent to try different approach
- System prompt teaches read-before-write, partial reads, grep filtering, change verification, done signaling
- 128 total tests (6 new), all green, zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add tests for loop improvements** - `3003e91` (test)
2. **Task 2a: Implement done-tool termination and turn logging** - `a885b69` (feat)
3. **Task 2b: Implement failure hints** - `bcb8d96` (feat)
4. **Task 2c: Implement system prompt** - `ff933e8` (feat)

## Files Created/Modified
- `tests/agents/test_loop.py` - 6 new tests: done termination (3), turn logging (1), failure hints (2)
- `src/ctx_rm/agents/loop.py` - Done detection, structlog turn_log, _consecutive_failures, _ingest_user_hint
- `src/ctx_rm/benchmarks/runner.py` - Comprehensive _build_system_prompt with workflow and tool tips

## Decisions Made
- Done tool coexists with other tools in same turn: all execute, then loop stops (not short-circuit)
- Failure hint injected as user-role message (OpenAI format allows user messages mid-conversation, not system)
- Failure counter resets both after success AND after hint injection (prevents double-hint)
- System prompt is tool-agnostic about internals: no mention of ctx-rm, eviction, budgets

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 01 (Agent Hardening) complete: both plans (01-01 tool upgrades, 01-02 loop improvements) done
- 128 tests passing, agent loop has done-tool termination, failure hints, comprehensive system prompt
- Ready for Phase 02 (Benchmark Suite)

## Self-Check: PASSED

All 4 files verified present. All 4 commit hashes verified in git log.

---
*Phase: 01-agent-hardening*
*Completed: 2026-02-08*
