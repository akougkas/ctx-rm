"""Experiment framework: YAML-driven multi-run benchmark comparisons.

Provides:
  - ExperimentConfig: Pydantic model for experiment YAML files
  - RunConfig: single combination to execute
  - RunResult: outcome of a single run
  - AggregatedResult: statistics aggregated across runs
  - ExperimentRunner: orchestrates all combinations via BenchmarkRunner
  - generate_combinations: cartesian product with mode-aware dedup
  - write_csv: export aggregated results to CSV
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable

import orjson
import structlog
import yaml
from pydantic import BaseModel

from ctx_rm.benchmarks.budget_map import BUDGET_MAP

logger = structlog.get_logger()


# ── Config model ─────────────────────────────────────────────────────────────


class ExperimentConfig(BaseModel):
    """Experiment configuration parsed from YAML."""

    name: str
    output_dir: str = "./results/experiments"
    runs: int = 3
    max_turns: int = 30
    tasks: list[str]
    modes: list[str]
    policies: list[str] = ["budget"]
    budgets: list[int] = []
    scorer: str = "heuristic"
    enable_recall: bool = False

    @classmethod
    def from_yaml(cls, path: Path) -> ExperimentConfig:
        """Read a YAML file and validate into an ExperimentConfig."""
        with path.open() as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)


# ── Combination types ────────────────────────────────────────────────────────


@dataclass
class RunConfig:
    """A single experiment combination to execute."""

    task_id: str
    mode: str
    policy: str | None
    budget: int
    run_index: int


@dataclass
class RunResult:
    """Outcome of a single benchmark run."""

    config: RunConfig
    passed: bool | None
    prompt_tokens: int
    completion_tokens: int
    eviction_count: int
    recall_count: int
    recall_precision: float
    error: str | None


@dataclass
class AggregatedResult:
    """Statistics aggregated across multiple runs of the same configuration."""

    task_id: str
    mode: str
    policy: str | None
    budget: int
    median_prompt_tokens: float
    pass_rate: float
    median_eviction_count: float
    median_recall_count: float
    mean_recall_precision: float
    num_runs: int
    num_errors: int


# ── Combination generator ────────────────────────────────────────────────────


def generate_combinations(config: ExperimentConfig) -> list[RunConfig]:
    """Generate all run combinations from an experiment config.

    Rules:
      - For ctx-rm mode: generates task x policy x budget x run_index combinations.
        If budgets is empty, budget=0 signals auto-select from BUDGET_MAP.
        If budgets is non-empty, one combination per budget value.
      - For non-ctx-rm modes (full, minimal): policy=None, budget=0.
        Deduped so each task x mode x run_index appears exactly once.
    """
    combos: list[RunConfig] = []
    seen: set[tuple[str, str, str | None, int, int]] = set()

    for task_id in config.tasks:
        for mode in config.modes:
            for run_idx in range(1, config.runs + 1):
                if mode == "ctx-rm":
                    budget_list = config.budgets if config.budgets else [0]
                    for policy in config.policies:
                        for budget_val in budget_list:
                            key = (task_id, mode, policy, budget_val, run_idx)
                            if key not in seen:
                                seen.add(key)
                                combos.append(RunConfig(
                                    task_id=task_id,
                                    mode=mode,
                                    policy=policy,
                                    budget=budget_val,
                                    run_index=run_idx,
                                ))
                else:
                    # Non-ctx-rm: dedup per task x mode x run
                    key = (task_id, mode, None, 0, run_idx)
                    if key not in seen:
                        seen.add(key)
                        combos.append(RunConfig(
                            task_id=task_id,
                            mode=mode,
                            policy=None,
                            budget=0,
                            run_index=run_idx,
                        ))

    combos.sort(key=lambda c: (
        c.task_id,
        c.mode,
        c.policy or "",
        c.budget,
        c.run_index,
    ))
    return combos


# ── Experiment runner ────────────────────────────────────────────────────────


class ExperimentRunner:
    """Orchestrates running all experiment combinations via BenchmarkRunner."""

    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config

    async def run_all(
        self,
        on_progress: Callable[[int, int, RunConfig], Any] | None = None,
    ) -> list[RunResult]:
        """Execute all combinations and return results."""
        from ctx_rm.benchmarks.runner import BenchmarkRunner

        combos = generate_combinations(self.config)
        results: list[RunResult] = []
        output_dir = Path(self.config.output_dir)

        for i, combo in enumerate(combos):
            if on_progress is not None:
                on_progress(i + 1, len(combos), combo)

            # Resolve budget: 0 means auto from BUDGET_MAP
            budget = combo.budget
            if combo.mode == "ctx-rm" and budget == 0:
                budget = BUDGET_MAP.get(combo.task_id, BenchmarkRunner.DEFAULT_TOKEN_BUDGET)

            try:
                runner = BenchmarkRunner(
                    driver_name="llamacpp",
                    task_id=combo.task_id,
                    mode=combo.mode,
                    token_budget=budget,
                    policy_name=combo.policy or "budget",
                    output_dir=output_dir,
                    run_index=combo.run_index,
                    max_turns=self.config.max_turns,
                    enable_recall=self.config.enable_recall,
                )
                await runner.run()

                # Read evaluation.json to extract results
                result_dir = runner._result_dir()
                eval_path = result_dir / "evaluation.json"

                if eval_path.exists():
                    eval_data = orjson.loads(eval_path.read_bytes())
                    agent = eval_data.get("agent_result", {})
                    results.append(RunResult(
                        config=combo,
                        passed=eval_data.get("all_passed"),
                        prompt_tokens=agent.get("prompt_tokens", 0),
                        completion_tokens=agent.get("completion_tokens", 0),
                        eviction_count=agent.get("segments_evicted", 0),
                        recall_count=agent.get("recalls_made", 0),
                        recall_precision=0.0,
                        error=None,
                    ))
                else:
                    results.append(RunResult(
                        config=combo,
                        passed=None,
                        prompt_tokens=0,
                        completion_tokens=0,
                        eviction_count=0,
                        recall_count=0,
                        recall_precision=0.0,
                        error="No evaluation.json produced",
                    ))

            except Exception as e:
                logger.error(
                    "experiment_run_failed",
                    task=combo.task_id,
                    mode=combo.mode,
                    error=str(e),
                )
                results.append(RunResult(
                    config=combo,
                    passed=None,
                    prompt_tokens=0,
                    completion_tokens=0,
                    eviction_count=0,
                    recall_count=0,
                    recall_precision=0.0,
                    error=str(e),
                ))

        return results

    @staticmethod
    def aggregate(results: list[RunResult]) -> list[AggregatedResult]:
        """Aggregate results by (task_id, mode, policy, budget).

        Computes median prompt tokens, pass rate, median eviction/recall counts,
        and mean recall precision across runs with the same configuration key.
        """
        groups: dict[tuple[str, str, str | None, int], list[RunResult]] = {}
        for r in results:
            key = (r.config.task_id, r.config.mode, r.config.policy, r.config.budget)
            groups.setdefault(key, []).append(r)

        aggregated: list[AggregatedResult] = []
        for (task_id, mode, policy, budget), group in sorted(groups.items()):
            successful = [r for r in group if r.error is None]
            num_errors = len(group) - len(successful)

            if successful:
                prompt_tokens_list = [r.prompt_tokens for r in successful]
                eviction_list = [r.eviction_count for r in successful]
                recall_list = [r.recall_count for r in successful]
                precision_list = [r.recall_precision for r in successful]
                passed_count = sum(1 for r in successful if r.passed is True)
                pass_rate = passed_count / len(successful)
                med_prompt = float(median(prompt_tokens_list))
                med_eviction = float(median(eviction_list))
                med_recall = float(median(recall_list))
                mean_precision = sum(precision_list) / len(precision_list)
            else:
                med_prompt = 0.0
                pass_rate = 0.0
                med_eviction = 0.0
                med_recall = 0.0
                mean_precision = 0.0

            aggregated.append(AggregatedResult(
                task_id=task_id,
                mode=mode,
                policy=policy,
                budget=budget,
                median_prompt_tokens=med_prompt,
                pass_rate=pass_rate,
                median_eviction_count=med_eviction,
                median_recall_count=med_recall,
                mean_recall_precision=mean_precision,
                num_runs=len(group),
                num_errors=num_errors,
            ))

        return aggregated


# ── CSV export ───────────────────────────────────────────────────────────────


def write_csv(results: list[AggregatedResult], path: Path) -> None:
    """Write aggregated results to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "task_id",
            "mode",
            "policy",
            "budget",
            "median_prompt_tokens",
            "pass_rate",
            "median_eviction_count",
            "median_recall_count",
            "mean_recall_precision",
            "num_runs",
            "num_errors",
        ])
        for r in results:
            writer.writerow([
                r.task_id,
                r.mode,
                r.policy or "",
                r.budget,
                f"{r.median_prompt_tokens:.0f}",
                f"{r.pass_rate:.2f}",
                f"{r.median_eviction_count:.0f}",
                f"{r.median_recall_count:.0f}",
                f"{r.mean_recall_precision:.4f}",
                r.num_runs,
                r.num_errors,
            ])
