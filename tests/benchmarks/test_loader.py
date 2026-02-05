"""Tests for the benchmark TaskLoader and Pydantic models."""

from pathlib import Path

import pytest

from ctx_rm.benchmarks.loader import TaskLoader
from ctx_rm.benchmarks.models import (
    FileContainsCheck,
    FileContainsInOrderCheck,
    FileEqualsCheck,
    FileNotContainsCheck,
)

YAML_PATH = Path("docs/context_removal_benchmark_tasks.yaml")


@pytest.fixture
def loader() -> TaskLoader:
    return TaskLoader(YAML_PATH)


def test_load_all_tasks(loader: TaskLoader) -> None:
    suite = loader.load()
    assert len(suite.tasks) == 10
    expected_ids = [f"CR-{i:03d}" for i in range(1, 11)]
    assert [t.id for t in suite.tasks] == expected_ids


def test_get_task_cr001(loader: TaskLoader) -> None:
    task = loader.get_task("CR-001")
    assert len(task.needles) == 2
    assert len(task.context_injections) == 1
    assert len(task.evaluation) == 2
    assert task.min_turns == 20


def test_get_task_not_found(loader: TaskLoader) -> None:
    with pytest.raises(ValueError, match="CR-999"):
        loader.get_task("CR-999")


def test_eval_check_discrimination(loader: TaskLoader) -> None:
    # CR-001: file_contains + file_equals
    cr001 = loader.get_task("CR-001")
    assert isinstance(cr001.evaluation[0], FileContainsCheck)
    assert isinstance(cr001.evaluation[1], FileEqualsCheck)

    # CR-002: file_contains_in_order
    cr002 = loader.get_task("CR-002")
    assert isinstance(cr002.evaluation[0], FileContainsInOrderCheck)

    # CR-007: file_not_contains present
    cr007 = loader.get_task("CR-007")
    not_contains = [e for e in cr007.evaluation if isinstance(e, FileNotContainsCheck)]
    assert len(not_contains) == 1


def test_needle_fields(loader: TaskLoader) -> None:
    task = loader.get_task("CR-001")
    n1 = next(n for n in task.needles if n.id == "N1")
    assert n1.injection_turn == 3
    assert n1.injection_method == "doc_read"
    assert n1.type == "fact"
