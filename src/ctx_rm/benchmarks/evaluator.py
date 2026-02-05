"""Evaluator: run assertion checks against files in a working directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ctx_rm.benchmarks.models import (
    EvalCheck,
    FileContainsCheck,
    FileContainsInOrderCheck,
    FileEqualsCheck,
    FileNotContainsCheck,
)


@dataclass
class CheckResult:
    """Result of a single evaluation check."""

    check_type: str
    target: str
    passed: bool
    detail: str


@dataclass
class EvaluationResult:
    """Aggregated result for all checks on a single task."""

    task_id: str
    results: list[CheckResult]

    @property
    def all_passed(self) -> bool:
        """True if every check passed."""
        return all(r.passed for r in self.results)

    @property
    def summary(self) -> str:
        """Human-readable one-line summary."""
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        return f"{self.task_id}: {passed}/{total} checks passed"


class Evaluator:
    """Run evaluation checks against files in a working directory.

    Args:
        working_dir: Root of the (temp-copied) fixture directory.
    """

    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir

    def run_checks(self, checks: list[EvalCheck]) -> list[CheckResult]:
        """Run all checks and return individual results."""
        return [self._run_check(c) for c in checks]

    def evaluate_task(
        self, task_id: str, checks: list[EvalCheck]
    ) -> EvaluationResult:
        """Convenience wrapper returning an :class:`EvaluationResult`."""
        return EvaluationResult(
            task_id=task_id,
            results=self.run_checks(checks),
        )

    def _run_check(self, check: EvalCheck) -> CheckResult:
        """Dispatch a single check to the appropriate handler."""
        target_path = self.working_dir / check.target
        if not target_path.exists():
            return CheckResult(
                check_type=check.check,
                target=check.target,
                passed=False,
                detail=f"File not found: {check.target}",
            )

        content = target_path.read_text()

        match check:
            case FileContainsCheck():
                passed = check.must_include in content
                detail = (
                    f"{'Found' if passed else 'Missing'}: {check.must_include!r}"
                )
            case FileNotContainsCheck():
                passed = check.must_include not in content
                detail = (
                    f"{'Absent (good)' if passed else 'Found (bad)'}: "
                    f"{check.must_include!r}"
                )
            case FileContainsInOrderCheck():
                passed = self._check_order(content, check.must_include_order)
                detail = (
                    f"Order {'correct' if passed else 'incorrect'}: "
                    f"{check.must_include_order}"
                )
            case FileEqualsCheck():
                passed = check.must_preserve in content
                detail = (
                    f"Content {'preserved' if passed else 'modified'}: "
                    f"{check.must_preserve!r}"
                )

        return CheckResult(
            check_type=check.check,
            target=check.target,
            passed=passed,
            detail=detail,
        )

    @staticmethod
    def _check_order(content: str, items: list[str]) -> bool:
        """Check that *items* appear in *content* in the given order.

        Each item must be found at a position strictly after the
        previous item's position.
        """
        last_pos = -1
        for item in items:
            pos = content.find(item, last_pos + 1)
            if pos == -1:
                return False
            last_pos = pos
        return True
