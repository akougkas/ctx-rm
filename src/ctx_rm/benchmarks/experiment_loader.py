"""Loader for machine-readable benchmark experiment matrices."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

from ctx_rm.benchmarks.models import ExperimentDefinition, ExperimentSuite

logger = structlog.get_logger()


class ExperimentLoader:
    """Load and query experiment suites from YAML files."""

    def __init__(self, yaml_path: Path) -> None:
        self._yaml_path = yaml_path
        self._suite: ExperimentSuite | None = None

    def load(self) -> ExperimentSuite:
        """Parse the YAML file and return a validated ExperimentSuite."""
        if not self._yaml_path.exists():
            raise FileNotFoundError(f"Experiment YAML not found: {self._yaml_path}")

        with self._yaml_path.open() as f:
            raw = yaml.safe_load(f)

        suite = ExperimentSuite.model_validate(raw)
        self._suite = suite

        logger.info(
            "experiment_suite_loaded",
            path=str(self._yaml_path),
            experiment_count=len(suite.experiments),
        )
        return suite

    def _ensure_loaded(self) -> ExperimentSuite:
        if self._suite is None:
            return self.load()
        return self._suite

    def get_experiment(self, experiment_id: str) -> ExperimentDefinition:
        """Return one experiment by ID."""
        suite = self._ensure_loaded()
        for experiment in suite.experiments:
            if experiment.id == experiment_id:
                return experiment
        raise ValueError(f"Experiment not found: {experiment_id}")

    def list_experiment_ids(self) -> list[str]:
        """Return experiment IDs in definition order."""
        suite = self._ensure_loaded()
        return [e.id for e in suite.experiments]

