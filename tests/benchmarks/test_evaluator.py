"""Tests for Evaluator and CheckResult/EvaluationResult."""

from pathlib import Path

import pytest

from ctx_rm.benchmarks.evaluator import EvaluationResult, Evaluator
from ctx_rm.benchmarks.models import (
    FileContainsCheck,
    FileContainsInOrderCheck,
    FileEqualsCheck,
    FileNotContainsCheck,
)


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Create a minimal working directory with test files."""
    (tmp_path / "src" / "auth").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "migrations").mkdir()

    (tmp_path / "src" / "auth" / "legacy.py").write_text(
        "def auth():\n    if LEGACY_AUTH:\n        pass\n"
    )
    (tmp_path / "config" / "flags.py").write_text(
        "LEGACY_AUTH = False\nSAFE_MODE = True\nDEBUG = False\n"
    )
    (tmp_path / "migrations" / "0042_fix_status.py").write_text(
        "def backfill_user_status():\n    pass\n\n"
        "def rename_column():\n    pass\n"
    )
    return tmp_path


# -- file_contains ----------------------------------------------------------


def test_file_contains_pass(work_dir: Path):
    check = FileContainsCheck(
        check="file_contains",
        target="src/auth/legacy.py",
        must_include="if LEGACY_AUTH:",
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert result.passed
    assert "Found" in result.detail


def test_file_contains_fail(work_dir: Path):
    check = FileContainsCheck(
        check="file_contains",
        target="src/auth/legacy.py",
        must_include="nonexistent_string_xyz",
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert not result.passed
    assert "Missing" in result.detail


# -- file_not_contains ------------------------------------------------------


def test_file_not_contains_pass(work_dir: Path):
    check = FileNotContainsCheck(
        check="file_not_contains",
        target="src/auth/legacy.py",
        must_include="timeout_ms",
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert result.passed
    assert "Absent" in result.detail


def test_file_not_contains_fail(work_dir: Path):
    check = FileNotContainsCheck(
        check="file_not_contains",
        target="src/auth/legacy.py",
        must_include="LEGACY_AUTH",
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert not result.passed
    assert "Found (bad)" in result.detail


# -- file_contains_in_order -------------------------------------------------


def test_file_contains_in_order_pass(work_dir: Path):
    check = FileContainsInOrderCheck(
        check="file_contains_in_order",
        target="migrations/0042_fix_status.py",
        must_include_order=["backfill_user_status", "rename_column"],
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert result.passed
    assert "correct" in result.detail


def test_file_contains_in_order_fail(work_dir: Path):
    check = FileContainsInOrderCheck(
        check="file_contains_in_order",
        target="migrations/0042_fix_status.py",
        must_include_order=["rename_column", "backfill_user_status"],
    )
    # The file has backfill first, then rename. Checking reverse order
    # should fail because rename_column appears *after* backfill, so
    # looking for backfill after rename would fail.
    # Actually let me reconsider: the file content is:
    # "def backfill_user_status():\n    pass\n\ndef rename_column():\n    pass\n"
    # So backfill_user_status is at position ~4, rename_column at ~38.
    # If we search for rename_column first: found at 38.
    # Then search for backfill_user_status after 38+1=39: NOT found (it's at 4).
    # So this should correctly fail.
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert not result.passed
    assert "incorrect" in result.detail


# -- file_equals (substring containment) ------------------------------------


def test_file_equals_pass(work_dir: Path):
    check = FileEqualsCheck(
        check="file_equals",
        target="config/flags.py",
        must_preserve="SAFE_MODE = True",
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert result.passed
    assert "preserved" in result.detail


def test_file_equals_fail(work_dir: Path):
    check = FileEqualsCheck(
        check="file_equals",
        target="config/flags.py",
        must_preserve="SAFE_MODE = False",
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert not result.passed
    assert "modified" in result.detail


# -- file not found ----------------------------------------------------------


def test_file_not_found(work_dir: Path):
    check = FileContainsCheck(
        check="file_contains",
        target="does/not/exist.py",
        must_include="anything",
    )
    ev = Evaluator(work_dir)
    result = ev.run_checks([check])[0]
    assert not result.passed
    assert "File not found" in result.detail


# -- EvaluationResult aggregation -------------------------------------------


def test_evaluate_task_all_passed(work_dir: Path):
    checks = [
        FileContainsCheck(
            check="file_contains",
            target="src/auth/legacy.py",
            must_include="if LEGACY_AUTH:",
        ),
        FileEqualsCheck(
            check="file_equals",
            target="config/flags.py",
            must_preserve="SAFE_MODE = True",
        ),
    ]
    ev = Evaluator(work_dir)
    result = ev.evaluate_task("CR-001", checks)
    assert isinstance(result, EvaluationResult)
    assert result.all_passed
    assert "2/2" in result.summary


def test_evaluate_task_some_failed(work_dir: Path):
    checks = [
        FileContainsCheck(
            check="file_contains",
            target="src/auth/legacy.py",
            must_include="if LEGACY_AUTH:",
        ),
        FileContainsCheck(
            check="file_contains",
            target="src/auth/legacy.py",
            must_include="nonexistent_thing",
        ),
    ]
    ev = Evaluator(work_dir)
    result = ev.evaluate_task("CR-001", checks)
    assert not result.all_passed
    assert "1/2" in result.summary
