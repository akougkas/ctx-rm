"""Tests for ExperimentLoader and experiment matrix schema validation."""

from pathlib import Path

import pytest

from ctx_rm.benchmarks.experiment_loader import ExperimentLoader

YAML_PATH = Path("docs/experiments/infmem_comparison.yaml")


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

