"""Tests for budget_map calibration and runner integration."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ctx_rm.benchmarks.budget_map import ADMISSION_THRESHOLD, BUDGET_MAP

YAML_PATH = Path("docs/context_removal_benchmark_tasks.yaml")


def _load_task_data() -> dict[str, dict]:
    """Load all tasks from YAML and compute token totals."""
    with YAML_PATH.open() as f:
        data = yaml.safe_load(f)

    result = {}
    for task in data["tasks"]:
        tid = task["id"]
        needle_tokens = sum(
            max(1, len(n["content"]) // 4) for n in task.get("needles", [])
        )
        noise_tokens = sum(
            inj["size_tokens"] for inj in task.get("context_injections", [])
        )
        overhead = 300  # system prompt ~200 + task instruction ~100
        total = needle_tokens + noise_tokens + overhead
        result[tid] = {
            "needle_tokens": needle_tokens,
            "noise_tokens": noise_tokens,
            "total": total,
        }
    return result


# ── Budget map coverage ──────────────────────────────────────────────────


class TestBudgetMapCoverage:
    """Ensure BUDGET_MAP covers all tasks from the YAML."""

    def test_budget_map_covers_all_tasks(self) -> None:
        """Every task ID in the YAML must have a BUDGET_MAP entry."""
        with YAML_PATH.open() as f:
            data = yaml.safe_load(f)

        yaml_ids = {t["id"] for t in data["tasks"]}
        map_ids = set(BUDGET_MAP.keys())

        missing = yaml_ids - map_ids
        assert not missing, f"Tasks missing from BUDGET_MAP: {missing}"

    def test_budget_map_has_no_extras(self) -> None:
        """BUDGET_MAP should not contain IDs absent from the YAML."""
        with YAML_PATH.open() as f:
            data = yaml.safe_load(f)

        yaml_ids = {t["id"] for t in data["tasks"]}
        extras = set(BUDGET_MAP.keys()) - yaml_ids
        assert not extras, f"Extra IDs in BUDGET_MAP not in YAML: {extras}"


# ── Budget range validation ──────────────────────────────────────────────


class TestBudgetRange:
    """Each budget must be between 30% and 70% of total injected tokens."""

    @pytest.fixture()
    def task_data(self) -> dict[str, dict]:
        return _load_task_data()

    def test_budgets_in_valid_range(self, task_data: dict[str, dict]) -> None:
        """Budget should be within [0.3 * total, 0.7 * total]."""
        for tid, info in task_data.items():
            total = info["total"]
            budget = BUDGET_MAP[tid]
            low = int(total * 0.3)
            high = int(total * 0.7)
            assert low <= budget <= high, (
                f"{tid}: budget={budget} outside [{low}, {high}] "
                f"(total={total})"
            )

    def test_budgets_in_strict_range(self, task_data: dict[str, dict]) -> None:
        """Budget should be within [0.4 * total, 0.6 * total] (plan spec)."""
        for tid, info in task_data.items():
            total = info["total"]
            budget = BUDGET_MAP[tid]
            low = int(total * 0.4)
            high = int(total * 0.6)
            assert low <= budget <= high, (
                f"{tid}: budget={budget} outside [{low}, {high}] "
                f"(total={total})"
            )


# ── Admission threshold ─────────────────────────────────────────────────


class TestAdmissionThreshold:
    """Validate the tuned admission threshold."""

    def test_admission_threshold_positive(self) -> None:
        assert ADMISSION_THRESHOLD > 0

    def test_admission_threshold_under_cap(self) -> None:
        assert ADMISSION_THRESHOLD < 5000

    def test_admission_threshold_reasonable(self) -> None:
        """Threshold should be within a reasonable range for file reads."""
        # The profiled P75 is ~4024; assert within ballpark
        assert 2000 <= ADMISSION_THRESHOLD <= 5000


# ── SCALE budget eviction guarantee ─────────────────────────────────────


class TestScaleBudgetsForceEviction:
    """For SCALE tasks the budget must be < 0.6 * total noise tokens."""

    @pytest.fixture()
    def task_data(self) -> dict[str, dict]:
        return _load_task_data()

    def test_scale_budgets_force_eviction(self, task_data: dict[str, dict]) -> None:
        """SCALE budgets below 60% of noise alone ensures heavy eviction."""
        scale_ids = [tid for tid in task_data if tid.startswith("SCALE-")]
        assert len(scale_ids) == 3, f"Expected 3 SCALE tasks, got {len(scale_ids)}"

        for tid in scale_ids:
            noise = task_data[tid]["noise_tokens"]
            budget = BUDGET_MAP[tid]
            threshold = int(noise * 0.6)
            assert budget < threshold, (
                f"{tid}: budget={budget} >= 0.6*noise={threshold} "
                f"(noise={noise})"
            )
