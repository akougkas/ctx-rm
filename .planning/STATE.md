# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-08)

**Core value:** An agent running with ctx-rm can process workloads exceeding its context window without accuracy degradation, proven by reproducible benchmarks.
**Current focus:** Phase 4 - Evidence (complete)

## Current Position

Phase: 4 of 4 (Evidence)
Plan: 2 of 2 in current phase
Status: Phase complete
Last activity: 2026-02-08 -- Completed 04-02 (Evidence Collection & Report)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 8
- Average duration: 8 min
- Total execution time: 69 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-agent-hardening | 2 | 7 min | 3.5 min |
| 02-scenarios-accuracy | 3 | 52 min | 17.3 min |
| 03-experiment-framework | 1 | 3 min | 3.0 min |
| 04-evidence | 2 | 7 min | 3.5 min |

**Recent Trend:**
- Last 5 plans: 02-03 (15 min), 03-01 (3 min), 04-01 (3 min), 04-02 (4 min)
- Trend: Consistent fast execution on focused plans

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
- Scale fixtures use realistic business/technical prose for noise, not lorem ipsum -- from 02-01
- SCALE-001/002/003 target 20K/30K/40K tokens with context_injections adding 17K-35K more -- from 02-01
- Budget target is 50% of total injected tokens (center of 40-60% range) -- from 02-03
- ADMISSION_THRESHOLD=4024 from P75 of 34 SCALE fixture file sizes -- from 02-03
- Runner auto-selects from BUDGET_MAP only in ctx-rm mode; explicit --budget overrides -- from 02-03
- Non-ctx-rm modes deduplicated in experiment combinations: policy/budget only expand for ctx-rm -- from 03-01
- budget=0 in RunConfig signals auto-select from BUDGET_MAP at runtime -- from 03-01
- Aggregation excludes errored runs from stats but counts them in num_errors -- from 03-01
- EvictionEvent.source tracks seg.source for post-hoc noise vs needle analysis -- from 04-01
- Analyzer walks result directory tree; structure mirrors BenchmarkRunner._result_dir output -- from 04-01
- Budget proxies for effective context window size in scaling experiments -- from 04-02
- Noise degradation uses 5 runs for statistical confidence -- from 04-02

### Pending Todos

None yet.

### Blockers/Concerns

- llama-server on mini:8080 must be running for integration tests
- Budget must be LOWER than total injected context to trigger eviction

## Session Continuity

Last session: 2026-02-08
Stopped at: Phase 4 complete. All 8 plans across 4 phases executed. Evidence infrastructure ready.
Resume file: SESSION-NEXT.md
