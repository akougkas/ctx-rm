"""TaskLoader: parse benchmark YAML into validated Pydantic models."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

from ctx_rm.benchmarks.models import BenchmarkSuite, Task

logger = structlog.get_logger()


class TaskLoader:
    """Load and query benchmark tasks from a YAML file.

    Args:
        yaml_path: Path to the benchmark YAML file.
    """

    def __init__(self, yaml_path: Path) -> None:
        self._yaml_path = yaml_path
        self._suite: BenchmarkSuite | None = None

    def load(self) -> BenchmarkSuite:
        """Parse the YAML file and return a validated BenchmarkSuite.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
        """
        if not self._yaml_path.exists():
            raise FileNotFoundError(f"Benchmark YAML not found: {self._yaml_path}")

        with self._yaml_path.open() as f:
            raw = yaml.safe_load(f)

        suite = BenchmarkSuite.model_validate(raw)
        self._suite = suite

        logger.info(
            "benchmark_suite_loaded",
            path=str(self._yaml_path),
            task_count=len(suite.tasks),
        )
        return suite

    def _ensure_loaded(self) -> BenchmarkSuite:
        """Return cached suite, loading on first call."""
        if self._suite is None:
            return self.load()
        return self._suite

    def get_task(self, task_id: str) -> Task:
        """Look up a task by its ID.

        Args:
            task_id: The task identifier (e.g. ``"CR-001"``).

        Raises:
            ValueError: If no task with the given ID exists.
        """
        suite = self._ensure_loaded()
        for task in suite.tasks:
            if task.id == task_id:
                return task
        raise ValueError(f"Task not found: {task_id}")

    def list_task_ids(self) -> list[str]:
        """Return all task IDs in definition order."""
        suite = self._ensure_loaded()
        return [t.id for t in suite.tasks]
