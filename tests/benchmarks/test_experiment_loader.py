"""Tests for ExperimentLoader and experiment matrix schema validation."""

from pathlib import Path

import pytest

from ctx_rm.benchmarks.experiment_loader import ExperimentLoader
from ctx_rm.benchmarks.loader import TaskLoader

YAML_PATH = Path("docs/experiments/infmem_comparison.yaml")
TASKS_YAML_PATH = Path("docs/context_removal_benchmark_tasks.yaml")


@pytest.fixture
def loader() -> ExperimentLoader:
    return ExperimentLoader(YAML_PATH)


def test_load_experiment_suite(loader: ExperimentLoader) -> None:
    suite = loader.load()
    assert suite.schema_version == 1
    assert suite.benchmark_name == "infmem_comparable_setup"
    assert len(suite.experiments) >= 3


def test_experiment_ids(loader: ExperimentLoader) -> None:
    ids = loader.list_experiment_ids()
    assert "EXP-COND-001" in ids
    assert "EXP-COST-001" in ids
    assert "EXP-NOISE-001" in ids


def test_get_experiment(loader: ExperimentLoader) -> None:
    exp = loader.get_experiment("EXP-COND-001")
    assert exp.control.mode == "ctx-rm"
    assert exp.challenger.mode == "ctx-rm"
    assert exp.control.scorer == "heuristic"
    assert exp.challenger.scorer == "sequential"


def test_get_experiment_missing(loader: ExperimentLoader) -> None:
    with pytest.raises(ValueError, match="EXP-DOES-NOT-EXIST"):
        loader.get_experiment("EXP-DOES-NOT-EXIST")


def test_all_experiment_tasks_exist_in_task_catalog(loader: ExperimentLoader) -> None:
    """All task IDs in the experiment matrix must exist in benchmark tasks YAML."""
    suite = loader.load()
    known_task_ids = set(TaskLoader(TASKS_YAML_PATH).list_task_ids())

    missing: list[tuple[str, str]] = []
    for experiment in suite.experiments:
        for task_id in experiment.tasks:
            if task_id not in known_task_ids:
                missing.append((experiment.id, task_id))

    assert not missing, f"Unknown task IDs in experiment matrix: {missing}"
