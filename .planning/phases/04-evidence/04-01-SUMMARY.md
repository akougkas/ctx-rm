---
phase: "04-evidence"
plan: "01"
subsystem: "telemetry, benchmarks, experiments"
tags: [evidence, analyzer, eviction-accuracy, recall, budget-knee]
dependency_graph:
  requires: ["03-01"]
  provides: ["evidence-analyzer", "experiment-configs", "eviction-source-tracking"]
  affects: ["04-02"]
tech_stack:
  added: []
  patterns: ["post-hoc analysis from metrics.json", "directory-tree walking for result aggregation"]
key_files:
  created:
    - src/ctx_rm/benchmarks/analyzer.py
    - tests/benchmarks/test_analyzer.py
    - docs/experiments/eviction_accuracy.yaml
    - docs/experiments/recall_effectiveness_on.yaml
    - docs/experiments/recall_effectiveness_off.yaml
    - docs/experiments/budget_sensitivity.yaml
  modified:
    - src/ctx_rm/telemetry/metrics.py
decisions: []
metrics:
  duration: "3 min"
  completed: "2026-02-08"
---

# Phase 4 Plan 1: Evidence Telemetry and Analyzer Summary

Source tracking in eviction events, four experiment YAML configs for EVID-01/02/03, and an analyzer module computing eviction accuracy, recall comparison, and budget knee from experiment output directories.

## What Was Done

### Task 1: EvictionEvent Source + Experiment YAML Configs

Added `source: str | None` field to `EvictionEvent` dataclass. Updated `record_eviction_cycle` to pass `seg.source` so eviction events in metrics.json now record whether the evicted segment was noise or needle.

Created four experiment YAML configs:
- `eviction_accuracy.yaml`: EVID-01 -- BudgetAware vs LRU on SCALE-001/002/003, recall off
- `recall_effectiveness_on.yaml`: EVID-02a -- ctx-rm vs full on SCALE-003, recall enabled
- `recall_effectiveness_off.yaml`: EVID-02b -- ctx-rm vs full on SCALE-003, recall disabled
- `budget_sensitivity.yaml`: EVID-03 -- budget sweep (500-100K) on SPEC-001

All configs parse via `ExperimentConfig.from_yaml`.

### Task 2: Evidence Analyzer Module

Created `src/ctx_rm/benchmarks/analyzer.py` with:

- `compute_eviction_accuracy(results_dir)` -- walks metrics.json files, groups eviction events by (task_id, policy), counts noise/needle/other sources, computes noise_ratio
- `compute_recall_comparison(recall_on_dir, recall_off_dir)` -- reads evaluation.json from both dirs, compares pass rates and token usage per task
- `compute_budget_knee(results_dir)` -- reads evaluation.json from budget sweep, builds pass_rate per budget level
- `find_knee_point(rows, full_mode_rate)` -- identifies lowest budget matching full-mode quality, computes token_savings_pct

All functions return typed dataclasses: `EvictionAccuracyRow`, `RecallComparisonRow`, `BudgetKneeRow`, `KneePoint`.

8 tests in `tests/benchmarks/test_analyzer.py` using synthetic fixtures in tmp_path.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- 167 tests pass (159 existing + 8 new), zero regressions
- All 4 YAML configs parse correctly via ExperimentConfig.from_yaml
- EvictionEvent source field serializes to metrics.json via __dict__
- All analyzer imports succeed

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 796f20e | feat(04-01): add source tracking to EvictionEvent and create experiment YAML configs |
| 2 | 11fec43 | feat(04-01): add evidence analyzer with eviction accuracy, recall comparison, and budget knee |
