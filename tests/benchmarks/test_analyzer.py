"""Tests for the evidence analyzer module."""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest

from ctx_rm.benchmarks.analyzer import (
    BudgetKneeRow,
    compute_budget_knee,
    compute_eviction_accuracy,
    compute_recall_comparison,
    compute_scaling_quality,
    find_knee_point,
    find_noise_degradation,
)


def _write_json(path: Path, data: dict) -> None:
    """Helper to write JSON data to a path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(data))


def _make_metrics(evictions: list[dict]) -> dict:
    """Build a minimal metrics.json structure."""
    return {
        "summary": {},
        "snapshots": [],
        "evictions": evictions,
        "recalls": [],
        "ingestions": [],
        "agent_responses": [],
    }


def _make_eval(passed: bool, prompt_tokens: int, eviction_count: int = 0, recalls_made: int = 0, budget: int = 0) -> dict:
    """Build a minimal evaluation.json structure."""
    data: dict = {
        "task_id": "TEST",
        "all_passed": passed,
        "summary": "test",
        "checks": [],
        "agent_result": {
            "turns": 5,
            "tool_calls": 10,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 100,
            "segments_evicted": eviction_count,
            "recalls_made": recalls_made,
        },
    }
    if budget:
        data["budget"] = budget
    return data


# ── Eviction accuracy ────────────────────────────────────────────────────────


class TestEvictionAccuracy:
    def test_counts_noise_vs_needle(self, tmp_path: Path) -> None:
        """Verify noise_ratio computation from eviction source fields."""
        # Create metrics.json with mixed sources
        run_dir = tmp_path / "SCALE-001" / "ctx-rm" / "llamacpp" / "budget" / "run-1"
        evictions = [
            {"seg_id": "a", "source": "noise:sales_report"},
            {"seg_id": "b", "source": "noise:readme"},
            {"seg_id": "c", "source": "noise:changelog"},
            {"seg_id": "d", "source": "needle:config_key"},
            {"seg_id": "e", "source": "file_read:src/main.py"},
        ]
        _write_json(run_dir / "metrics.json", _make_metrics(evictions))

        rows = compute_eviction_accuracy(tmp_path)
        assert len(rows) == 1

        row = rows[0]
        assert row.task_id == "SCALE-001"
        assert row.policy == "budget"
        assert row.noise_evictions == 3
        assert row.needle_evictions == 1
        assert row.other_evictions == 1
        assert row.noise_ratio == pytest.approx(0.75)
        assert row.total_evictions == 5

    def test_handles_no_evictions(self, tmp_path: Path) -> None:
        """Empty evictions list returns zero counts and None noise_ratio."""
        run_dir = tmp_path / "SCALE-001" / "ctx-rm" / "llamacpp" / "lru" / "run-1"
        _write_json(run_dir / "metrics.json", _make_metrics([]))

        rows = compute_eviction_accuracy(tmp_path)
        assert len(rows) == 1

        row = rows[0]
        assert row.noise_evictions == 0
        assert row.needle_evictions == 0
        assert row.other_evictions == 0
        assert row.noise_ratio is None
        assert row.total_evictions == 0

    def test_aggregates_across_runs(self, tmp_path: Path) -> None:
        """Evictions from multiple runs are aggregated per (task, policy)."""
        for run_idx in [1, 2]:
            run_dir = tmp_path / "SCALE-002" / "ctx-rm" / "llamacpp" / "budget" / f"run-{run_idx}"
            evictions = [
                {"seg_id": f"n{run_idx}", "source": "noise:data"},
                {"seg_id": f"k{run_idx}", "source": "needle:key"},
            ]
            _write_json(run_dir / "metrics.json", _make_metrics(evictions))

        rows = compute_eviction_accuracy(tmp_path)
        assert len(rows) == 1

        row = rows[0]
        assert row.noise_evictions == 2
        assert row.needle_evictions == 2
        assert row.noise_ratio == pytest.approx(0.5)
        assert row.total_evictions == 4

    def test_supports_experiment_root_layout(self, tmp_path: Path) -> None:
        """Works when task paths are nested under an experiment directory."""
        run_dir = (
            tmp_path / "eviction-accuracy" / "SCALE-001" / "ctx-rm"
            / "llamacpp" / "budget" / "run-1"
        )
        _write_json(run_dir / "metrics.json", _make_metrics([
            {"seg_id": "n1", "source": "noise:data"},
            {"seg_id": "k1", "source": "needle:key"},
        ]))

        # full mode metrics should be ignored for eviction-accuracy analysis
        full_dir = tmp_path / "eviction-accuracy" / "SCALE-001" / "full" / "llamacpp" / "run-1"
        _write_json(full_dir / "metrics.json", _make_metrics([
            {"seg_id": "x1", "source": "noise:irrelevant"},
        ]))

        rows = compute_eviction_accuracy(tmp_path)
        assert len(rows) == 1
        assert rows[0].task_id == "SCALE-001"
        assert rows[0].policy == "budget"
        assert rows[0].total_evictions == 2


# ── Recall comparison ─────────────────────────────────────────────────────────


class TestRecallComparison:
    def test_pass_rates(self, tmp_path: Path) -> None:
        """Compare pass rates between recall-on and recall-off directories."""
        on_dir = tmp_path / "recall-on"
        off_dir = tmp_path / "recall-off"

        # Recall ON: 2/3 pass
        for i, passed in enumerate([True, True, False], 1):
            path = on_dir / "SCALE-003" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=passed, prompt_tokens=5000, recalls_made=3))

        # Recall OFF: 1/3 pass
        for i, passed in enumerate([True, False, False], 1):
            path = off_dir / "SCALE-003" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=passed, prompt_tokens=4000, recalls_made=0))

        rows = compute_recall_comparison(on_dir, off_dir)
        assert len(rows) == 1

        row = rows[0]
        assert row.task_id == "SCALE-003"
        assert row.pass_rate_on == pytest.approx(2 / 3)
        assert row.pass_rate_off == pytest.approx(1 / 3)
        assert row.median_tokens_on == 5000.0
        assert row.median_tokens_off == 4000.0
        assert row.recall_count_median == 3.0

    def test_missing_one_side(self, tmp_path: Path) -> None:
        """Tasks only in one directory get zeros for the missing side."""
        on_dir = tmp_path / "recall-on"
        off_dir = tmp_path / "recall-off"

        # Only recall-on has data
        path = on_dir / "SCALE-003" / "ctx-rm" / "llamacpp" / "budget" / "run-1" / "evaluation.json"
        _write_json(path, _make_eval(passed=True, prompt_tokens=5000, recalls_made=2))

        # recall-off is empty
        off_dir.mkdir(parents=True, exist_ok=True)

        rows = compute_recall_comparison(on_dir, off_dir)
        assert len(rows) == 1

        row = rows[0]
        assert row.pass_rate_on == 1.0
        assert row.pass_rate_off == 0.0

    def test_filters_to_ctx_rm_mode_only(self, tmp_path: Path) -> None:
        """Recall comparison should ignore full-mode runs."""
        on_dir = tmp_path / "recall-on"
        off_dir = tmp_path / "recall-off"

        # ctx-rm differs across on/off
        _write_json(
            on_dir / "SCALE-003" / "ctx-rm" / "llamacpp" / "budget" / "run-1" / "evaluation.json",
            _make_eval(passed=True, prompt_tokens=5000, recalls_made=2),
        )
        _write_json(
            off_dir / "SCALE-003" / "ctx-rm" / "llamacpp" / "budget" / "run-1" / "evaluation.json",
            _make_eval(passed=False, prompt_tokens=4000, recalls_made=0),
        )

        # full mode should not affect comparison
        _write_json(
            on_dir / "SCALE-003" / "full" / "llamacpp" / "run-1" / "evaluation.json",
            _make_eval(passed=True, prompt_tokens=99999, recalls_made=0),
        )
        _write_json(
            off_dir / "SCALE-003" / "full" / "llamacpp" / "run-1" / "evaluation.json",
            _make_eval(passed=True, prompt_tokens=99999, recalls_made=0),
        )

        rows = compute_recall_comparison(on_dir, off_dir)
        assert len(rows) == 1
        row = rows[0]
        assert row.pass_rate_on == 1.0
        assert row.pass_rate_off == 0.0
        assert row.median_tokens_on == 5000.0
        assert row.median_tokens_off == 4000.0


# ── Budget knee ───────────────────────────────────────────────────────────────


class TestBudgetKnee:
    def test_finds_lowest_matching(self) -> None:
        """Identify the lowest budget where pass_rate >= full_mode_rate."""
        rows = [
            BudgetKneeRow(task_id="SPEC-001", budget=500, pass_rate=0.0, median_prompt_tokens=400, median_eviction_count=20),
            BudgetKneeRow(task_id="SPEC-001", budget=2000, pass_rate=0.33, median_prompt_tokens=1800, median_eviction_count=15),
            BudgetKneeRow(task_id="SPEC-001", budget=8000, pass_rate=0.67, median_prompt_tokens=6000, median_eviction_count=8),
            BudgetKneeRow(task_id="SPEC-001", budget=32000, pass_rate=1.0, median_prompt_tokens=20000, median_eviction_count=3),
            BudgetKneeRow(task_id="SPEC-001", budget=1_000_000, pass_rate=1.0, median_prompt_tokens=50000, median_eviction_count=0),
        ]

        knee = find_knee_point(rows, full_mode_rate=1.0)
        assert knee is not None
        assert knee.knee_budget == 32000
        assert knee.full_mode_tokens == 50000
        assert knee.knee_tokens == 20000
        assert knee.token_savings_pct == pytest.approx(60.0)

    def test_returns_none_when_no_match(self) -> None:
        """All pass rates below full mode returns None."""
        rows = [
            BudgetKneeRow(task_id="SPEC-001", budget=500, pass_rate=0.0, median_prompt_tokens=400, median_eviction_count=20),
            BudgetKneeRow(task_id="SPEC-001", budget=2000, pass_rate=0.33, median_prompt_tokens=1800, median_eviction_count=15),
            BudgetKneeRow(task_id="SPEC-001", budget=1_000_000, pass_rate=1.0, median_prompt_tokens=50000, median_eviction_count=0),
        ]

        knee = find_knee_point(rows, full_mode_rate=1.0)
        assert knee is None

    def test_compute_from_directory(self, tmp_path: Path) -> None:
        """compute_budget_knee reads evaluation.json and builds rows."""
        # Create ctx-rm runs at budget=4000
        for i in range(1, 4):
            path = tmp_path / "SPEC-001" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(
                passed=(i <= 2),
                prompt_tokens=3000 + i * 100,
                eviction_count=5,
                budget=4000,
            ))

        # Create full-mode runs
        for i in range(1, 4):
            path = tmp_path / "SPEC-001" / "full" / "llamacpp" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(
                passed=True,
                prompt_tokens=30000 + i * 100,
                eviction_count=0,
            ))

        rows = compute_budget_knee(tmp_path)
        assert len(rows) == 2  # One for budget=4000, one for full mode

        # Verify the ctx-rm row
        ctx_row = [r for r in rows if r.budget == 4000][0]
        assert ctx_row.task_id == "SPEC-001"
        assert ctx_row.pass_rate == pytest.approx(2 / 3)
        assert ctx_row.median_prompt_tokens == 3200.0  # median of 3100, 3200, 3300

        # Verify the full row
        full_row = [r for r in rows if r.budget == 1_000_000][0]
        assert full_row.pass_rate == 1.0


# ── Scaling quality ──────────────────────────────────────────────────────────


class TestScalingQuality:
    def test_extracts_per_budget_rates(self, tmp_path: Path) -> None:
        """compute_scaling_quality groups ctx-rm runs by budget and includes full baseline."""
        # ctx-rm at budget=4000: 2/3 pass
        for i, passed in enumerate([True, True, False], 1):
            path = tmp_path / "SCALE-001" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=passed, prompt_tokens=3000 + i * 100, budget=4000))

        # ctx-rm at budget=8000: 3/3 pass
        for i in range(1, 4):
            path = tmp_path / "SCALE-001" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}" / "evaluation.json"
            # Need different budget dir to avoid collision — use metrics.json approach
            alt_dir = tmp_path / "SCALE-001-b8k" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}"
            _write_json(alt_dir / "evaluation.json", _make_eval(passed=True, prompt_tokens=6000 + i * 100, budget=8000))

        # full mode: 3/3 pass
        for i in range(1, 4):
            path = tmp_path / "SCALE-001" / "full" / "llamacpp" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=True, prompt_tokens=30000))

        rows = compute_scaling_quality(tmp_path)

        # Should have 2 ctx-rm rows (budget=4000, budget=8000)
        ctx_rows = [r for r in rows if r.budget > 0]
        assert len(ctx_rows) == 2

        row_4k = [r for r in ctx_rows if r.budget == 4000][0]
        assert row_4k.task_id == "SCALE-001"
        assert row_4k.pass_rate == pytest.approx(2 / 3)
        assert row_4k.median_prompt_tokens == 3200.0  # median of 3100, 3200, 3300
        assert row_4k.full_mode_pass_rate == 1.0

        row_8k = [r for r in ctx_rows if r.budget == 8000][0]
        assert row_8k.pass_rate == 1.0


# ── Noise degradation ────────────────────────────────────────────────────────


class TestNoiseDegradation:
    def test_identifies_candidate(self, tmp_path: Path) -> None:
        """Task where ctx-rm passes more than full is a degradation candidate."""
        # ctx-rm: 3/3 pass
        for i in range(1, 4):
            path = tmp_path / "SCALE-002" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=True, prompt_tokens=5000))

        # full: 1/3 pass (noise causes failures)
        for i, passed in enumerate([True, False, False], 1):
            path = tmp_path / "SCALE-002" / "full" / "llamacpp" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=passed, prompt_tokens=30000))

        rows = find_noise_degradation(tmp_path)
        assert len(rows) == 1

        row = rows[0]
        assert row.task_id == "SCALE-002"
        assert row.ctx_rm_pass_rate == 1.0
        assert row.full_pass_rate == pytest.approx(1 / 3)
        assert row.delta == pytest.approx(2 / 3)
        assert row.is_degradation_candidate is True
        assert row.num_runs == 6

    def test_no_candidate(self, tmp_path: Path) -> None:
        """Task where full passes equally or better is NOT a degradation candidate."""
        # ctx-rm: 2/3 pass
        for i, passed in enumerate([True, True, False], 1):
            path = tmp_path / "SCALE-003" / "ctx-rm" / "llamacpp" / "budget" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=passed, prompt_tokens=5000))

        # full: 3/3 pass
        for i in range(1, 4):
            path = tmp_path / "SCALE-003" / "full" / "llamacpp" / f"run-{i}" / "evaluation.json"
            _write_json(path, _make_eval(passed=True, prompt_tokens=30000))

        rows = find_noise_degradation(tmp_path)
        assert len(rows) == 1

        row = rows[0]
        assert row.task_id == "SCALE-003"
        assert row.ctx_rm_pass_rate == pytest.approx(2 / 3)
        assert row.full_pass_rate == 1.0
        assert row.delta == pytest.approx(-1 / 3)
        assert row.is_degradation_candidate is False
