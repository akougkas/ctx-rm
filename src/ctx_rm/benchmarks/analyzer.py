"""Evidence analyzer: computes metrics from experiment output directories.

Reads metrics.json and evaluation.json produced by BenchmarkRunner and computes:
  - Eviction accuracy (noise vs needle eviction ratio)
  - Recall comparison (pass rate with/without recall)
  - Budget knee point (lowest budget matching full-mode quality)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median

import orjson


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class EvictionAccuracyRow:
    """Eviction accuracy for a (task_id, policy) group."""

    task_id: str
    policy: str
    noise_evictions: int
    needle_evictions: int
    other_evictions: int
    noise_ratio: float | None  # None when no noise+needle evictions
    total_evictions: int


@dataclass
class RecallComparisonRow:
    """Comparison of recall-on vs recall-off for a task."""

    task_id: str
    pass_rate_on: float
    pass_rate_off: float
    median_tokens_on: float
    median_tokens_off: float
    recall_count_median: float


@dataclass
class BudgetKneeRow:
    """Single budget level result for knee analysis."""

    task_id: str
    budget: int
    pass_rate: float
    median_prompt_tokens: float
    median_eviction_count: float


@dataclass
class KneePoint:
    """Identified budget knee point."""

    task_id: str
    knee_budget: int
    full_mode_tokens: float
    knee_tokens: float
    token_savings_pct: float


# ── Analysis functions ────────────────────────────────────────────────────────


def compute_eviction_accuracy(results_dir: Path) -> list[EvictionAccuracyRow]:
    """Compute eviction accuracy from experiment output.

    Walks the results directory tree to find metrics.json files, extracts
    eviction events with source field, and groups by (task_id, policy).

    Directory structure expected:
      {results_dir}/{task_id}/ctx-rm/{driver}/{policy}/run-{N}/metrics.json
    """
    # Collect eviction events grouped by (task_id, policy)
    groups: dict[tuple[str, str], list[dict]] = {}

    for metrics_path in results_dir.rglob("metrics.json"):
        parts = metrics_path.relative_to(results_dir).parts
        # Expected: task_id / ctx-rm / driver / policy / run-N / metrics.json
        if len(parts) < 6:
            continue
        task_id = parts[0]
        policy = parts[3]

        data = orjson.loads(metrics_path.read_bytes())
        evictions = data.get("evictions", [])

        key = (task_id, policy)
        groups.setdefault(key, []).extend(evictions)

    rows: list[EvictionAccuracyRow] = []
    for (task_id, policy), evictions in sorted(groups.items()):
        noise = sum(1 for e in evictions if (e.get("source") or "").startswith("noise:"))
        needle = sum(1 for e in evictions if (e.get("source") or "").startswith("needle:"))
        other = len(evictions) - noise - needle

        if noise + needle > 0:
            noise_ratio: float | None = noise / (noise + needle)
        else:
            noise_ratio = None

        rows.append(EvictionAccuracyRow(
            task_id=task_id,
            policy=policy,
            noise_evictions=noise,
            needle_evictions=needle,
            other_evictions=other,
            noise_ratio=noise_ratio,
            total_evictions=len(evictions),
        ))

    return rows


def compute_recall_comparison(
    recall_on_dir: Path,
    recall_off_dir: Path,
) -> list[RecallComparisonRow]:
    """Compare pass rates and token usage between recall-on and recall-off experiments.

    Reads evaluation.json from both directories and groups by task_id.

    Directory structure expected:
      {dir}/{task_id}/{mode}/{driver}/[{policy}/]run-{N}/evaluation.json
    """
    on_data = _collect_eval_data(recall_on_dir)
    off_data = _collect_eval_data(recall_off_dir)

    # Merge on task_id
    all_tasks = sorted(set(on_data.keys()) | set(off_data.keys()))

    rows: list[RecallComparisonRow] = []
    for task_id in all_tasks:
        on_runs = on_data.get(task_id, [])
        off_runs = off_data.get(task_id, [])

        pass_on = _pass_rate(on_runs) if on_runs else 0.0
        pass_off = _pass_rate(off_runs) if off_runs else 0.0
        med_tok_on = float(median([r["prompt_tokens"] for r in on_runs])) if on_runs else 0.0
        med_tok_off = float(median([r["prompt_tokens"] for r in off_runs])) if off_runs else 0.0
        recall_counts = [r.get("recalls_made", 0) for r in on_runs]
        med_recall = float(median(recall_counts)) if recall_counts else 0.0

        rows.append(RecallComparisonRow(
            task_id=task_id,
            pass_rate_on=pass_on,
            pass_rate_off=pass_off,
            median_tokens_on=med_tok_on,
            median_tokens_off=med_tok_off,
            recall_count_median=med_recall,
        ))

    return rows


def compute_budget_knee(results_dir: Path) -> list[BudgetKneeRow]:
    """Compute pass rate and token usage at each budget level.

    Reads evaluation.json and metrics.json from budget sweep results.

    Directory structure expected:
      ctx-rm runs: {results_dir}/{task_id}/ctx-rm/{driver}/{policy}/run-{N}/
      full runs:   {results_dir}/{task_id}/full/{driver}/run-{N}/
    """
    # Collect runs grouped by (task_id, budget)
    groups: dict[tuple[str, int], list[dict]] = {}

    for eval_path in results_dir.rglob("evaluation.json"):
        parts = eval_path.relative_to(results_dir).parts
        if len(parts) < 4:
            continue

        task_id = parts[0]
        mode = parts[1]

        eval_data = orjson.loads(eval_path.read_bytes())
        agent = eval_data.get("agent_result", {})

        if mode == "full":
            # Full mode = effectively unlimited budget
            budget = 1_000_000
        elif mode == "ctx-rm":
            # Extract budget from the run's metrics or use directory structure
            # Budget is stored in the evaluation data or inferred from config
            budget = eval_data.get("budget", 0)
            if budget == 0:
                # Try reading from metrics.json alongside
                metrics_path = eval_path.parent / "metrics.json"
                if metrics_path.exists():
                    metrics_data = orjson.loads(metrics_path.read_bytes())
                    budget = metrics_data.get("budget", 0)
        else:
            continue

        run_info = {
            "passed": eval_data.get("all_passed"),
            "prompt_tokens": agent.get("prompt_tokens", 0),
            "eviction_count": agent.get("segments_evicted", 0),
            "recalls_made": agent.get("recalls_made", 0),
        }

        key = (task_id, budget)
        groups.setdefault(key, []).append(run_info)

    rows: list[BudgetKneeRow] = []
    for (task_id, budget), runs in sorted(groups.items()):
        pass_rate = _pass_rate(runs)
        med_tokens = float(median([r["prompt_tokens"] for r in runs]))
        med_evictions = float(median([r["eviction_count"] for r in runs]))

        rows.append(BudgetKneeRow(
            task_id=task_id,
            budget=budget,
            pass_rate=pass_rate,
            median_prompt_tokens=med_tokens,
            median_eviction_count=med_evictions,
        ))

    return rows


def find_knee_point(
    rows: list[BudgetKneeRow],
    full_mode_rate: float,
) -> KneePoint | None:
    """Find the lowest budget where pass_rate >= full_mode_rate.

    Scans rows in ascending budget order. Returns None if no budget meets
    the threshold.
    """
    sorted_rows = sorted(rows, key=lambda r: r.budget)

    # Find the full-mode row for token comparison
    full_rows = [r for r in sorted_rows if r.budget >= 1_000_000]
    full_tokens = full_rows[0].median_prompt_tokens if full_rows else 0.0

    for row in sorted_rows:
        if row.budget >= 1_000_000:
            continue  # Skip full-mode rows
        if row.pass_rate >= full_mode_rate:
            savings = (
                (1.0 - row.median_prompt_tokens / full_tokens) * 100.0
                if full_tokens > 0
                else 0.0
            )
            return KneePoint(
                task_id=row.task_id,
                knee_budget=row.budget,
                full_mode_tokens=full_tokens,
                knee_tokens=row.median_prompt_tokens,
                token_savings_pct=savings,
            )

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _collect_eval_data(results_dir: Path) -> dict[str, list[dict]]:
    """Collect evaluation data grouped by task_id from a results directory."""
    groups: dict[str, list[dict]] = {}

    for eval_path in results_dir.rglob("evaluation.json"):
        parts = eval_path.relative_to(results_dir).parts
        if len(parts) < 4:
            continue
        task_id = parts[0]

        eval_data = orjson.loads(eval_path.read_bytes())
        agent = eval_data.get("agent_result", {})

        run_info = {
            "passed": eval_data.get("all_passed"),
            "prompt_tokens": agent.get("prompt_tokens", 0),
            "recalls_made": agent.get("recalls_made", 0),
        }

        groups.setdefault(task_id, []).append(run_info)

    return groups


def _pass_rate(runs: list[dict]) -> float:
    """Compute pass rate from a list of run info dicts."""
    if not runs:
        return 0.0
    passed = sum(1 for r in runs if r.get("passed") is True)
    return passed / len(runs)
