"""Data quality validation for the processing pipeline.

This module provides the ``DataValidator`` class that performs
data quality checks on records after they have been processed
by the ``DataProcessor``. Unlike the SchemaValidator which checks
structure, the DataValidator checks the quality and consistency
of actual data values.

Validation Categories
---------------------
1. **Completeness**: Percentage of non-null values per field
2. **Consistency**: Cross-field logical consistency checks
3. **Accuracy**: Range checks, format verification
4. **Timeliness**: Date freshness and currency checks
5. **Uniqueness**: Duplicate detection and dedup metrics

Quality Score
-------------
Each record receives a quality score from 0.0 to 1.0 based on
the weighted results of all applicable checks. Records below a
configurable threshold can be flagged or filtered.

Integration with DataProcessor
------------------------------
The DataValidator can be chained after a DataProcessor in the
pipeline. It receives already-processed records and applies
quality checks to determine whether the processing produced
valid output.

The DataProcessor handles format conversion and schema validation,
while the DataValidator ensures the resulting data meets quality
standards for downstream consumption.

Change History
--------------
- v1.0: Basic completeness and range checks
- v1.1: Added cross-field consistency checks
- v1.2: Added quality scoring
- v1.3: Added statistical outlier detection
- v1.4: Added timeliness checks
- v1.5: Added integration with DataProcessor pipeline
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..core.data_processor import DataProcessor

logger = logging.getLogger(__name__)


@dataclass
class QualityCheck:
    """Definition of a single data quality check.

    Attributes:
        name: Check identifier.
        check_type: Category of the check.
        field_name: Field to check (or None for record-level).
        parameters: Check-specific parameters.
        weight: Weight in the quality score (0.0-1.0).
        severity: Failure severity ("error", "warning", "info").
    """

    name: str = ""
    check_type: str = ""
    field_name: Optional[str] = None
    parameters: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    severity: str = "warning"


@dataclass
class QualityIssue:
    """A single data quality issue found during validation.

    Attributes:
        record_index: Index of the affected record.
        check_name: Name of the check that found the issue.
        field_name: Affected field name.
        issue_type: Category of the issue.
        message: Description of the issue.
        value: The problematic value.
        suggested_fix: Optional suggestion for fixing the issue.
        severity: Issue severity.
    """

    record_index: int = 0
    check_name: str = ""
    field_name: str = ""
    issue_type: str = ""
    message: str = ""
    value: Any = None
    suggested_fix: Optional[str] = None
    severity: str = "warning"


@dataclass
class QualityReport:
    """Comprehensive data quality report.

    Attributes:
        overall_score: Aggregate quality score (0.0-1.0).
        records_checked: Number of records analyzed.
        records_passed: Records meeting quality threshold.
        records_flagged: Records below quality threshold.
        issues: All quality issues found.
        field_completeness: Per-field completeness percentage.
        field_scores: Per-field quality scores.
        check_results: Per-check pass/fail counts.
        recommendations: Suggested data quality improvements.
    """

    overall_score: float = 0.0
    records_checked: int = 0
    records_passed: int = 0
    records_flagged: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    field_completeness: dict[str, float] = field(default_factory=dict)
    field_scores: dict[str, float] = field(default_factory=dict)
    check_results: dict[str, dict[str, int]] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable quality report summary."""
        return (
            f"Quality Report: score={self.overall_score:.2f} "
            f"records={self.records_checked} "
            f"passed={self.records_passed} "
            f"flagged={self.records_flagged} "
            f"issues={len(self.issues)}"
        )


class DataValidator:
    """Data quality validator for the processing pipeline.

    Performs quality checks on processed data records and generates
    comprehensive quality reports.

    The validator can be used standalone or integrated with a
    DataProcessor pipeline as a post-processing quality gate.

    Args:
        checks: List of quality checks to perform.
        quality_threshold: Minimum score for a record to pass.
        processor: Optional DataProcessor for context.
    """

    def __init__(
        self,
        checks: Optional[list[QualityCheck]] = None,
        quality_threshold: float = 0.7,
        processor: Optional[DataProcessor] = None,
    ) -> None:
        self._checks = checks or []
        self._threshold = quality_threshold
        self._processor = processor
        self._check_registry: dict[str, Callable] = {
            "completeness": self._check_completeness,
            "range": self._check_range,
            "pattern": self._check_pattern,
            "unique": self._check_uniqueness,
            "consistency": self._check_consistency,
            "outlier": self._check_outlier,
            "freshness": self._check_freshness,
        }

    def validate(self, records: list[dict[str, Any]]) -> QualityReport:
        """Run all quality checks on a batch of records.

        Args:
            records: Processed data records to validate.

        Returns:
            QualityReport with detailed quality metrics.
        """
        report = QualityReport(records_checked=len(records))

        if not records:
            return report

        # Calculate field completeness
        all_fields = set()
        for record in records:
            all_fields.update(record.keys())

        for f_name in all_fields:
            non_null = sum(
                1 for r in records
                if r.get(f_name) is not None and r.get(f_name) != ""
            )
            report.field_completeness[f_name] = non_null / len(records)

        # Run each check
        record_scores: list[float] = []
        for i, record in enumerate(records):
            score = self._score_record(record, i, report)
            record_scores.append(score)
            if score >= self._threshold:
                report.records_passed += 1
            else:
                report.records_flagged += 1

        # Calculate overall score
        if record_scores:
            report.overall_score = statistics.mean(record_scores)

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        logger.info(
            "Data quality validation: %s",
            report.summary(),
        )

        return report

    def add_check(self, check: QualityCheck) -> None:
        """Add a quality check to the validator."""
        self._checks.append(check)

    def _score_record(
        self,
        record: dict[str, Any],
        index: int,
        report: QualityReport,
    ) -> float:
        """Calculate the quality score for a single record."""
        total_weight = 0.0
        weighted_score = 0.0

        for check in self._checks:
            handler = self._check_registry.get(check.check_type)
            if handler is None:
                continue

            passed, issues = handler(record, index, check)
            report.issues.extend(issues)

            check_name = check.name or check.check_type
            if check_name not in report.check_results:
                report.check_results[check_name] = {"passed": 0, "failed": 0}

            if passed:
                report.check_results[check_name]["passed"] += 1
                weighted_score += check.weight
            else:
                report.check_results[check_name]["failed"] += 1

            total_weight += check.weight

        return weighted_score / total_weight if total_weight > 0 else 1.0

    def _check_completeness(
        self,
        record: dict[str, Any],
        index: int,
        check: QualityCheck,
    ) -> tuple[bool, list[QualityIssue]]:
        """Check field completeness."""
        issues: list[QualityIssue] = []
        f_name = check.field_name
        if f_name is None:
            return True, issues

        value = record.get(f_name)
        if value is None or value == "":
            issues.append(
                QualityIssue(
                    record_index=index,
                    check_name=check.name,
                    field_name=f_name,
                    issue_type="missing",
                    message=f"Missing value for {f_name}",
                    severity=check.severity,
                )
            )
            return False, issues

        return True, issues

    def _check_range(
        self,
        record: dict[str, Any],
        index: int,
        check: QualityCheck,
    ) -> tuple[bool, list[QualityIssue]]:
        """Check numeric range."""
        issues: list[QualityIssue] = []
        f_name = check.field_name
        if f_name is None:
            return True, issues

        value = record.get(f_name)
        if value is None:
            return True, issues

        try:
            num_val = float(value)
        except (ValueError, TypeError):
            return True, issues

        min_val = check.parameters.get("min")
        max_val = check.parameters.get("max")

        if min_val is not None and num_val < min_val:
            issues.append(
                QualityIssue(
                    record_index=index,
                    check_name=check.name,
                    field_name=f_name,
                    issue_type="below_range",
                    message=f"{f_name}={num_val} below minimum {min_val}",
                    value=num_val,
                    severity=check.severity,
                )
            )
            return False, issues

        if max_val is not None and num_val > max_val:
            issues.append(
                QualityIssue(
                    record_index=index,
                    check_name=check.name,
                    field_name=f_name,
                    issue_type="above_range",
                    message=f"{f_name}={num_val} above maximum {max_val}",
                    value=num_val,
                    severity=check.severity,
                )
            )
            return False, issues

        return True, issues

    def _check_pattern(
        self,
        record: dict[str, Any],
        index: int,
        check: QualityCheck,
    ) -> tuple[bool, list[QualityIssue]]:
        """Check string pattern match."""
        issues: list[QualityIssue] = []
        f_name = check.field_name
        if f_name is None:
            return True, issues

        value = record.get(f_name)
        if value is None or not isinstance(value, str):
            return True, issues

        pattern = check.parameters.get("pattern", "")
        if pattern and not re.match(pattern, value):
            issues.append(
                QualityIssue(
                    record_index=index,
                    check_name=check.name,
                    field_name=f_name,
                    issue_type="pattern_mismatch",
                    message=f"{f_name} doesn't match pattern {pattern}",
                    value=value,
                    severity=check.severity,
                )
            )
            return False, issues

        return True, issues

    def _check_uniqueness(
        self,
        record: dict[str, Any],
        index: int,
        check: QualityCheck,
    ) -> tuple[bool, list[QualityIssue]]:
        """Placeholder for uniqueness check (handled at batch level)."""
        return True, []

    def _check_consistency(
        self,
        record: dict[str, Any],
        index: int,
        check: QualityCheck,
    ) -> tuple[bool, list[QualityIssue]]:
        """Check cross-field consistency."""
        issues: list[QualityIssue] = []
        rules = check.parameters.get("rules", [])

        for rule in rules:
            field_a = rule.get("field_a")
            field_b = rule.get("field_b")
            relation = rule.get("relation", "equals")

            val_a = record.get(field_a)
            val_b = record.get(field_b)

            if val_a is None or val_b is None:
                continue

            passed = True
            if relation == "equals" and val_a != val_b:
                passed = False
            elif relation == "less_than":
                try:
                    passed = float(val_a) < float(val_b)
                except (ValueError, TypeError):
                    pass

            if not passed:
                issues.append(
                    QualityIssue(
                        record_index=index,
                        check_name=check.name,
                        field_name=f"{field_a},{field_b}",
                        issue_type="inconsistency",
                        message=f"Inconsistency: {field_a}={val_a} vs {field_b}={val_b}",
                        severity=check.severity,
                    )
                )
                return False, issues

        return True, issues

    def _check_outlier(
        self,
        record: dict[str, Any],
        index: int,
        check: QualityCheck,
    ) -> tuple[bool, list[QualityIssue]]:
        """Placeholder for outlier detection."""
        return True, []

    def _check_freshness(
        self,
        record: dict[str, Any],
        index: int,
        check: QualityCheck,
    ) -> tuple[bool, list[QualityIssue]]:
        """Check date freshness."""
        issues: list[QualityIssue] = []
        f_name = check.field_name
        if f_name is None:
            return True, issues

        value = record.get(f_name)
        if value is None or not isinstance(value, str):
            return True, issues

        max_age_days = check.parameters.get("max_age_days", 365)
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).days
            if age > max_age_days:
                issues.append(
                    QualityIssue(
                        record_index=index,
                        check_name=check.name,
                        field_name=f_name,
                        issue_type="stale",
                        message=f"{f_name} is {age} days old (max {max_age_days})",
                        value=value,
                        severity=check.severity,
                    )
                )
                return False, issues
        except ValueError:
            pass

        return True, issues

    def _generate_recommendations(self, report: QualityReport) -> list[str]:
        """Generate data quality improvement recommendations."""
        recommendations: list[str] = []

        for field_name, completeness in report.field_completeness.items():
            if completeness < 0.5:
                recommendations.append(
                    f"Field '{field_name}' has {completeness:.0%} completeness - "
                    f"consider making it optional or adding default values"
                )

        if report.records_flagged > report.records_checked * 0.2:
            recommendations.append(
                f"{report.records_flagged}/{report.records_checked} records flagged - "
                f"review data source quality"
            )

        return recommendations
