# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-08)

**Core value:** An agent running with ctx-rm can process workloads exceeding its context window without accuracy degradation, proven by reproducible benchmarks.
**Current focus:** Phase 2 - Scenarios & Accuracy (in progress)

## Current Position

Phase: 2 of 4 (Scenarios & Accuracy)
Plan: 2 of 3 in current phase
Status: In progress
Last activity: 2026-02-08 -- Completed 02-02-PLAN.md (Scorer Weights & Content Recall)

Progress: [████░░░░░░] 40%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 3.3 min
- Total execution time: 10 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-agent-hardening | 2 | 7 min | 3.5 min |
| 02-scenarios-accuracy | 1 | 3 min | 3 min |

**Recent Trend:**
- Last 5 plans: 01-01 (3 min), 01-02 (4 min), 02-02 (3 min)
- Trend: stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Architecture locked: AgentLoop + LlamaCppDriver + llama-server. No alternatives.
- BudgetAwarePolicy + source_weight=0.3 is recommended default (pending validation)
- Recall source filter: needle/context/user_task/user_message ONLY
- exit_code format: [exit_code: N] (underscore, always emitted) -- from 01-01
- file_read backward compat: no line numbers without range params -- from 01-01
- grep default includes: module-level _DEFAULT_INCLUDES list -- from 01-01
- Done tool coexists with other tools in same turn (all execute, then loop stops) -- from 01-02
- Failure hint as user-role message with source="system_hint" -- from 01-02
- Failure counter resets after success AND after hint injection -- from 01-02
- System prompt teaches tool usage without mentioning ctx-rm internals -- from 01-02
- Content recall searches by file path + result snippet (not just task text) -- from 02-02
- Content recall allows recalling tool segments (broadened from safe-source filter) -- from 02-02
- Recall precision uses 100-char content overlap as hit detection -- from 02-02
- Default recall_budget=3 per turn; 0 disables recall -- from 02-02

### Pending Todos

None yet.

### Blockers/Concerns

- llama-server on mini:8080 must be running for integration tests
- Budget must be LOWER than total injected context to trigger eviction

## Session Continuity

Last session: 2026-02-08
Stopped at: Completed 02-02-PLAN.md (Scorer Weights & Content Recall)
Resume file: .planning/phases/02-scenarios-accuracy/02-03-PLAN.md
