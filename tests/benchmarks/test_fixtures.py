"""Tests for FixtureManager."""

from pathlib import Path

import pytest

from ctx_rm.benchmarks.fixtures import FixtureManager

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "benchmarks" / "fixtures"


@pytest.fixture
def fm() -> FixtureManager:
    return FixtureManager(FIXTURES_ROOT)


def test_list_fixtures(fm: FixtureManager):
    """FixtureManager lists all 10 fixture directories."""
    fixtures = fm.list_fixtures()
    assert len(fixtures) == 10
    assert "legacy_flag_cascade" in fixtures
    assert "multi_issue_thread" in fixtures


def test_create_working_copy(fm: FixtureManager):
    """Working copy contains the fixture's files."""
    work_dir = fm.create_working_copy("legacy_flag_cascade")
    try:
        assert work_dir.exists()
        assert (work_dir / "config" / "flags.py").exists()
        assert (work_dir / "src" / "auth" / "legacy.py").exists()
    finally:
        fm.cleanup(work_dir)


def test_working_copy_is_independent(fm: FixtureManager):
    """Modifications to the working copy do not affect the source."""
    work_dir = fm.create_working_copy("legacy_flag_cascade")
    try:
        sentinel = work_dir / "sentinel.txt"
        sentinel.write_text("test")
        assert sentinel.exists()
        # Source must NOT have the sentinel
        assert not (FIXTURES_ROOT / "legacy_flag_cascade" / "sentinel.txt").exists()
    finally:
        fm.cleanup(work_dir)


def test_resolve_fixture_name():
    """resolve_fixture_name extracts the directory name from repo_fixture."""
    name = FixtureManager.resolve_fixture_name("fixtures/legacy_flag_cascade")
    assert name == "legacy_flag_cascade"
    name = FixtureManager.resolve_fixture_name("fixtures/multi_issue_thread")
    assert name == "multi_issue_thread"


def test_fixture_not_found(fm: FixtureManager):
    """FileNotFoundError raised for nonexistent fixture."""
    with pytest.raises(FileNotFoundError):
        fm.create_working_copy("nonexistent_fixture")
