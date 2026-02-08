# Session Goal: Budget Calibration + Experiment Runs

## Context

Legacy cleanup is done. Event system, TUI dashboard, consolidated test harness —
all complete. 108 tests passing. The codebase is clean.

**The blocker now is budget calibration.** Current benchmark tasks don't generate
enough context to trigger eviction at the default 100K budget. Without eviction
pressure, we can't demonstrate the value of ctx-rm's policies/scorers.

## What This Session Should Do

### 1. Budget Calibration

For each of the 13 tasks, determine:
- How many tokens of context get injected (needles + noise)?
- What budget triggers meaningful eviction (>2 eviction cycles)?
- Set per-task calibrated budgets in the YAML or as CLI defaults

The goal: every task in ctx-rm mode should experience real eviction pressure.
Some tasks may need larger noise injections in the YAML.

### 2. Multi-Run Experiments

Once budgets are calibrated:
- Run each task 5x per config (3 modes × 5 policies × 5 runs)
- Compute median + CI for: prompt tokens, evictions, pass rate
- Store results in results/ directory
- Verify the three cascading claims hold:
  1. SequentialScorer > HeuristicScorer (conditional > independent)
  2. Adaptive weights reduce page faults vs static
  3. ctx-rm matches full-context quality at lower token cost

### 3. Response Logging

Currently only metrics.json and evaluation.json are written per-run.
Add response_log.jsonl (agent responses per turn) for debugging and analysis.

## Verification

1. `uv run ctx-rm bench --task SPEC-001 --mode ctx-rm --budget 1500 --enable-recall --max-turns 10` — eviction fires, task passes
2. All 13 tasks with calibrated budgets show eviction activity
3. Multi-run results show statistical significance for claims

## Rules

- Budget must be LOWER than total injected context to trigger eviction
- Always `uv pip install -e .` after editing source
- Stage files individually, never `git add .`
- Run tests after every major change
