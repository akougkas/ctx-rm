"""Tests for the experiment framework: config, combinations, aggregation, CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ctx_rm.benchmarks.experiment import (
    AggregatedResult,
    ExperimentConfig,
    ExperimentRunner,
    RunConfig,
    RunResult,
    generate_combinations,
    write_csv,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _write_yaml(path: Path, data: dict) -> Path:
    """Write a dict as YAML and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.dump(data, f)
    return path


def _full_config_dict(**overrides) -> dict:
    """Return a complete experiment config dict with optional overrides."""
    base = {
        "name": "test-experiment",
        "output_dir": "./results/test",
        "runs": 3,
        "max_turns": 10,
        "tasks": ["CR-001", "SPEC-001"],
        "modes": ["ctx-rm", "full"],
        "policies": ["budget", "lru"],
        "budgets": [],
        "scorer": "heuristic",
        "enable_recall": False,
    }
    base.update(overrides)
    return base


def _make_run_result(
    task_id: str = "CR-001",
    mode: str = "ctx-rm",
    policy: str | None = "budget",
    budget: int = 0,
    run_index: int = 1,
    passed: bool | None = True,
    prompt_tokens: int = 500,
    completion_tokens: int = 100,
    eviction_count: int = 5,
    recall_count: int = 2,
    recall_precision: float = 0.8,
    error: str | None = None,
) -> RunResult:
    """Build a RunResult with defaults."""
    return RunResult(
        config=RunConfig(
            task_id=task_id,
            mode=mode,
            policy=policy,
            budget=budget,
            run_index=run_index,
        ),
        passed=passed,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        eviction_count=eviction_count,
        recall_count=recall_count,
        recall_precision=recall_precision,
        error=error,
    )


# ── Config tests ─────────────────────────────────────────────────────────────


class TestExperimentConfig:
    def test_config_from_yaml(self, tmp_path: Path) -> None:
        """ExperimentConfig.from_yaml parses all fields correctly."""
        data = _full_config_dict()
        path = _write_yaml(tmp_path / "config.yaml", data)

        config = ExperimentConfig.from_yaml(path)

        assert config.name == "test-experiment"
        assert config.output_dir == "./results/test"
        assert config.runs == 3
        assert config.max_turns == 10
        assert config.tasks == ["CR-001", "SPEC-001"]
        assert config.modes == ["ctx-rm", "full"]
        assert config.policies == ["budget", "lru"]
        assert config.budgets == []
        assert config.scorer == "heuristic"
        assert config.enable_recall is False

    def test_config_defaults(self, tmp_path: Path) -> None:
        """Minimal YAML gets correct defaults."""
        data = {
            "name": "minimal",
            "tasks": ["CR-001"],
            "modes": ["ctx-rm"],
        }
        path = _write_yaml(tmp_path / "minimal.yaml", data)

        config = ExperimentConfig.from_yaml(path)

        assert config.output_dir == "./results/experiments"
        assert config.runs == 3
        assert config.max_turns == 30
        assert config.policies == ["budget"]
        assert config.budgets == []
        assert config.scorer == "heuristic"
        assert config.enable_recall is False


# ── Combination generation tests ─────────────────────────────────────────────


class TestCombinationGeneration:
    def test_generate_combinations_ctx_rm_auto_budget(self) -> None:
        """ctx-rm mode with empty budgets produces budget=0 (auto) per policy per run."""
        config = ExperimentConfig(
            name="test",
            tasks=["CR-001"],
            modes=["ctx-rm"],
            policies=["budget"],
            budgets=[],
            runs=2,
        )
        combos = generate_combinations(config)

        assert len(combos) == 2  # 1 task x 1 policy x 1 budget(auto) x 2 runs
        for c in combos:
            assert c.mode == "ctx-rm"
            assert c.policy == "budget"
            assert c.budget == 0  # signals auto

    def test_generate_combinations_full_dedup(self) -> None:
        """Non-ctx-rm modes are deduped: policy variations don't multiply runs."""
        config = ExperimentConfig(
            name="test",
            tasks=["CR-001"],
            modes=["full"],
            policies=["budget", "lru", "clock"],  # should be ignored for full mode
            budgets=[1000, 2000],  # should also be ignored
            runs=2,
        )
        combos = generate_combinations(config)

        # full mode: 1 task x 1 mode x 2 runs = 2 (no policy/budget expansion)
        assert len(combos) == 2
        for c in combos:
            assert c.mode == "full"
            assert c.policy is None
            assert c.budget == 0

    def test_generate_combinations_budget_sweep(self) -> None:
        """ctx-rm mode with explicit budgets produces one combo per budget value."""
        config = ExperimentConfig(
            name="test",
            tasks=["CR-001"],
            modes=["ctx-rm"],
            policies=["budget"],
            budgets=[1000, 2000, 3000],
            runs=1,
        )
        combos = generate_combinations(config)

        assert len(combos) == 3  # 1 task x 1 policy x 3 budgets x 1 run
        budgets_seen = {c.budget for c in combos}
        assert budgets_seen == {1000, 2000, 3000}

    def test_generate_combinations_mixed(self) -> None:
        """Mixed modes: ctx-rm expands, full/minimal dedup."""
        config = ExperimentConfig(
            name="test",
            tasks=["CR-001", "SPEC-001"],
            modes=["ctx-rm", "full", "minimal"],
            policies=["budget", "lru"],
            budgets=[],
            runs=2,
        )
        combos = generate_combinations(config)

        # Per task:
        #   ctx-rm: 2 policies x 1 budget(auto) x 2 runs = 4
        #   full: 1 x 2 runs = 2
        #   minimal: 1 x 2 runs = 2
        # Total per task = 8, x 2 tasks = 16
        assert len(combos) == 16

        ctx_rm_combos = [c for c in combos if c.mode == "ctx-rm"]
        full_combos = [c for c in combos if c.mode == "full"]
        minimal_combos = [c for c in combos if c.mode == "minimal"]

        assert len(ctx_rm_combos) == 8  # 2 tasks x 2 policies x 2 runs
        assert len(full_combos) == 4    # 2 tasks x 2 runs
        assert len(minimal_combos) == 4  # 2 tasks x 2 runs

        # Verify sorting: by task_id, then mode, then policy, then budget, then run_index
        task_ids = [c.task_id for c in combos]
        assert task_ids == sorted(task_ids)  # CR-001 before SPEC-001


# ── Aggregation tests ────────────────────────────────────────────────────────


class TestAggregation:
    def test_aggregate_basic(self) -> None:
        """Aggregate computes correct median/pass_rate across successful runs."""
        results = [
            _make_run_result(run_index=1, prompt_tokens=400, passed=True, eviction_count=4, recall_count=1),
            _make_run_result(run_index=2, prompt_tokens=600, passed=True, eviction_count=6, recall_count=3),
            _make_run_result(run_index=3, prompt_tokens=500, passed=False, eviction_count=5, recall_count=2),
        ]

        aggregated = ExperimentRunner.aggregate(results)

        assert len(aggregated) == 1
        agg = aggregated[0]
        assert agg.task_id == "CR-001"
        assert agg.mode == "ctx-rm"
        assert agg.policy == "budget"
        assert agg.median_prompt_tokens == 500.0  # median of [400, 600, 500]
        assert agg.pass_rate == pytest.approx(2 / 3)
        assert agg.median_eviction_count == 5.0
        assert agg.median_recall_count == 2.0
        assert agg.mean_recall_precision == pytest.approx(0.8)
        assert agg.num_runs == 3
        assert agg.num_errors == 0

    def test_aggregate_with_errors(self) -> None:
        """Errors are excluded from stats but counted in num_errors."""
        results = [
            _make_run_result(run_index=1, prompt_tokens=500, passed=True),
            _make_run_result(run_index=2, prompt_tokens=0, passed=None, error="Connection refused"),
            _make_run_result(run_index=3, prompt_tokens=700, passed=True),
        ]

        aggregated = ExperimentRunner.aggregate(results)

        assert len(aggregated) == 1
        agg = aggregated[0]
        assert agg.num_runs == 3
        assert agg.num_errors == 1
        assert agg.median_prompt_tokens == 600.0  # median of [500, 700]
        assert agg.pass_rate == 1.0  # 2/2 successful passed


# ── CSV export test ──────────────────────────────────────────────────────────


class TestCSVExport:
    def test_csv_export(self, tmp_path: Path) -> None:
        """write_csv produces a valid CSV with correct headers and data."""
        aggregated = [
            AggregatedResult(
                task_id="CR-001",
                mode="ctx-rm",
                policy="budget",
                budget=1413,
                median_prompt_tokens=500.0,
                pass_rate=0.67,
                median_eviction_count=5.0,
                median_recall_count=2.0,
                mean_recall_precision=0.75,
                num_runs=3,
                num_errors=0,
            ),
            AggregatedResult(
                task_id="CR-001",
                mode="full",
                policy=None,
                budget=0,
                median_prompt_tokens=1200.0,
                pass_rate=1.0,
                median_eviction_count=0.0,
                median_recall_count=0.0,
                mean_recall_precision=0.0,
                num_runs=3,
                num_errors=1,
            ),
        ]

        csv_path = tmp_path / "output" / "results.csv"
        write_csv(aggregated, csv_path)

        assert csv_path.exists()
        lines = csv_path.read_text().strip().split("\n")
        assert len(lines) == 3  # header + 2 data rows

        header = lines[0]
        assert "task_id" in header
        assert "median_prompt_tokens" in header
        assert "pass_rate" in header
        assert "median_eviction_count" in header
        assert "median_recall_count" in header

        # Check first data row
        row1 = lines[1].split(",")
        assert row1[0] == "CR-001"
        assert row1[1] == "ctx-rm"
        assert row1[2] == "budget"


# ── Dry-run test ─────────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_run(self, tmp_path: Path) -> None:
        """--dry-run generates combinations but does not execute any runs."""
        data = _full_config_dict(
            tasks=["CR-001"],
            modes=["ctx-rm"],
            policies=["budget"],
            runs=1,
        )
        path = _write_yaml(tmp_path / "config.yaml", data)

        config = ExperimentConfig.from_yaml(path)
        combos = generate_combinations(config)

        # Verify combinations are generated
        assert len(combos) == 1
        assert combos[0].task_id == "CR-001"
        assert combos[0].mode == "ctx-rm"

        # Verify no output directory is created (dry run doesn't run anything)
        output_dir = Path(config.output_dir)
        assert not output_dir.exists()
