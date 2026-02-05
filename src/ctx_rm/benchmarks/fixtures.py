"""FixtureManager: copy benchmark fixture directories to isolated temp locations."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


class FixtureManager:
    """Manage benchmark fixture directories.

    Each benchmark task has a corresponding fixture directory containing
    a small "codebase" that the agent works on.  Before running a
    benchmark, the fixture is copied to a temp directory so that
    modifications do not affect the source.

    Args:
        fixtures_root: Root directory containing fixture subdirectories.
    """

    def __init__(self, fixtures_root: Path) -> None:
        self.fixtures_root = fixtures_root

    def create_working_copy(self, fixture_name: str) -> Path:
        """Copy a fixture directory to a temp directory.

        Args:
            fixture_name: Name of the fixture subdirectory.

        Returns:
            Path to the temp directory containing the copied fixture.

        Raises:
            FileNotFoundError: If the fixture directory does not exist.
        """
        src = self.fixtures_root / fixture_name
        if not src.exists():
            raise FileNotFoundError(f"Fixture not found: {src}")
        tmp = Path(tempfile.mkdtemp(prefix=f"ctx-rm-{fixture_name}-"))
        shutil.copytree(src, tmp, dirs_exist_ok=True)
        return tmp

    @staticmethod
    def cleanup(working_dir: Path) -> None:
        """Remove a working copy directory.

        Args:
            working_dir: Path previously returned by :meth:`create_working_copy`.
        """
        shutil.rmtree(working_dir, ignore_errors=True)

    @staticmethod
    def resolve_fixture_name(repo_fixture: str) -> str:
        """Extract fixture directory name from a YAML ``repo_fixture`` field.

        Example::

            >>> FixtureManager.resolve_fixture_name("fixtures/legacy_flag_cascade")
            'legacy_flag_cascade'

        Args:
            repo_fixture: The ``repo_fixture`` value from the task YAML.
        """
        return Path(repo_fixture).name

    def list_fixtures(self) -> list[str]:
        """Return sorted list of fixture directory names."""
        return sorted(
            d.name
            for d in self.fixtures_root.iterdir()
            if d.is_dir()
        )
