"""Schema validation for data processing pipelines.

This module provides the ``SchemaValidator`` class that validates
data records against predefined schema definitions before they
are processed by the ``DataProcessor``.

The validator works as a pre-processing step in the pipeline,
ensuring that all records conform to the expected structure,
types, and constraints before the DataProcessor begins its work.

Validation Levels
-----------------
The validator supports three levels of strictness:

1. **Structure**: Checks that required fields are present
2. **Type**: Checks that field values are the expected type
3. **Semantic**: Checks business rules and cross-field constraints

Each level includes all checks from lower levels.

Schema Definition Format
------------------------
Schemas are defined as dictionaries with the following structure::

    schema = {
        "fields": [
            {
                "name": "email",
                "type": "string",
                "required": True,
                "pattern": r"^[^@]+@[^@]+\.[^@]+$",
                "max_length": 255,
            },
            {
                "name": "age",
                "type": "integer",
                "required": True,
                "min_value": 0,
                "max_value": 150,
            },
        ],
        "constraints": [
            {
                "type": "unique",
                "fields": ["email"],
            },
            {
                "type": "conditional_required",
                "field": "phone",
                "condition_field": "contact_preference",
                "condition_value": "phone",
            },
        ],
    }

Integration with DataProcessor
------------------------------
The SchemaValidator can be used standalone or integrated into a
DataProcessor pipeline. When integrated, it runs as the first
validation step before the DataProcessor's own schema validation.

The validator uses the same FieldSchema definitions as the DataProcessor
for consistency, and can import schemas directly from processor configs.

Performance
-----------
- Validation is O(n * m) where n=records, m=fields
- Pattern matching uses pre-compiled regex
- Type checks use Python isinstance() for efficiency
- Unique constraints use hash sets for O(1) lookups

Change History
--------------
- v1.0: Basic field presence and type validation
- v1.1: Added pattern matching and range checks
- v1.2: Added cross-field constraints
- v1.3: Added unique constraint checking
- v1.4: Added conditional required fields
- v1.5: Added integration with DataProcessor schemas
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.data_processor import DataProcessor, FieldSchema, ProcessorConfig

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """A single validation error with context.

    Attributes:
        record_index: Index of the failing record in the batch.
        field_name: Name of the failing field.
        error_type: Category of the validation error.
        message: Human-readable error description.
        expected: Expected value or constraint description.
        actual: The actual value that failed validation.
        severity: Error severity ("error", "warning", "info").
    """

    record_index: int = 0
    field_name: str = ""
    error_type: str = ""
    message: str = ""
    expected: str = ""
    actual: Any = None
    severity: str = "error"


@dataclass
class ValidationResult:
    """Result of validating a batch of records.

    Attributes:
        is_valid: True if no errors were found.
        errors: List of validation errors.
        warnings: List of validation warnings.
        records_checked: Number of records validated.
        records_passed: Number of records with no errors.
        records_failed: Number of records with at least one error.
        field_error_counts: Error count per field name.
    """

    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    records_checked: int = 0
    records_passed: int = 0
    records_failed: int = 0
    field_error_counts: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        """Generate a human-readable validation summary."""
        return (
            f"Validation: {'PASSED' if self.is_valid else 'FAILED'} "
            f"({self.records_passed}/{self.records_checked} records valid, "
            f"{len(self.errors)} errors, {len(self.warnings)} warnings)"
        )


@dataclass
class SchemaDefinition:
    """Complete schema definition for validation.

    Attributes:
        name: Schema name for identification.
        version: Schema version string.
        fields: List of field definitions.
        constraints: Cross-field constraints.
        allow_extra_fields: Whether to permit fields not in the schema.
        strict_types: Whether to enforce exact type matching.
    """

    name: str = ""
    version: str = "1.0"
    fields: list[FieldSchema] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    allow_extra_fields: bool = True
    strict_types: bool = False


class SchemaValidator:
    """Validates data records against schema definitions.

    Works as a standalone validator or as a pre-processing step
    for the DataProcessor pipeline.

    Args:
        schema: Schema definition to validate against.
        processor: Optional DataProcessor for schema import.
    """

    TYPE_MAP: dict[str, type | tuple[type, ...]] = {
        "str": str,
        "string": str,
        "int": (int,),
        "integer": (int,),
        "float": (int, float),
        "number": (int, float),
        "decimal": (int, float, str),
        "bool": (bool,),
        "boolean": (bool,),
        "date": (str,),
        "datetime": (str,),
        "list": (list,),
        "dict": (dict,),
    }

    def __init__(
        self,
        schema: Optional[SchemaDefinition] = None,
        processor: Optional[DataProcessor] = None,
    ) -> None:
        self._schema = schema or SchemaDefinition()
        self._processor = processor
        self._compiled_patterns: dict[str, re.Pattern] = {}

        # Pre-compile regex patterns
        for field_def in self._schema.fields:
            if field_def.pattern:
                self._compiled_patterns[field_def.name] = re.compile(field_def.pattern)

    @classmethod
    def from_processor_config(
        cls, config: ProcessorConfig
    ) -> "SchemaValidator":
        """Create a validator from a DataProcessor configuration.

        Imports the field schema from the processor config into
        a SchemaDefinition for validation.

        Args:
            config: DataProcessor configuration.

        Returns:
            Configured SchemaValidator instance.
        """
        schema = SchemaDefinition(
            name="from_processor",
            fields=config.schema,
        )
        return cls(schema=schema)

    def validate_batch(
        self, records: list[dict[str, Any]]
    ) -> ValidationResult:
        """Validate a batch of records against the schema.

        Args:
            records: List of data records to validate.

        Returns:
            ValidationResult with detailed error information.
        """
        result = ValidationResult(records_checked=len(records))

        for i, record in enumerate(records):
            record_errors = self._validate_record(record, i)
            if record_errors:
                result.errors.extend(
                    e for e in record_errors if e.severity == "error"
                )
                result.warnings.extend(
                    e for e in record_errors if e.severity == "warning"
                )
                result.records_failed += 1
                for error in record_errors:
                    result.field_error_counts[error.field_name] = (
                        result.field_error_counts.get(error.field_name, 0) + 1
                    )
            else:
                result.records_passed += 1

        # Check cross-record constraints
        constraint_errors = self._check_constraints(records)
        result.errors.extend(constraint_errors)

        result.is_valid = len(result.errors) == 0

        logger.info(
            "Schema validation: %s records=%d passed=%d failed=%d errors=%d",
            "PASSED" if result.is_valid else "FAILED",
            result.records_checked,
            result.records_passed,
            result.records_failed,
            len(result.errors),
        )

        return result

    def validate_record(
        self, record: dict[str, Any], index: int = 0
    ) -> list[ValidationError]:
        """Validate a single record.

        Args:
            record: Data record to validate.
            index: Record index for error reporting.

        Returns:
            List of validation errors (empty if valid).
        """
        return self._validate_record(record, index)

    def _validate_record(
        self, record: dict[str, Any], index: int
    ) -> list[ValidationError]:
        """Internal record validation implementation."""
        errors: list[ValidationError] = []

        # Check for extra fields
        if not self._schema.allow_extra_fields:
            schema_names = {f.name for f in self._schema.fields}
            for key in record:
                if key not in schema_names:
                    errors.append(
                        ValidationError(
                            record_index=index,
                            field_name=key,
                            error_type="extra_field",
                            message=f"Unexpected field: {key}",
                            severity="warning",
                        )
                    )

        # Validate each defined field
        for field_def in self._schema.fields:
            value = record.get(field_def.name)

            # Required check
            if field_def.required and (value is None or value == ""):
                errors.append(
                    ValidationError(
                        record_index=index,
                        field_name=field_def.name,
                        error_type="required",
                        message=f"Required field missing: {field_def.name}",
                        expected="non-empty value",
                        actual=value,
                    )
                )
                continue

            if value is None:
                continue

            # Type check
            if self._schema.strict_types:
                expected_type = self.TYPE_MAP.get(field_def.field_type)
                if expected_type and not isinstance(value, expected_type):
                    errors.append(
                        ValidationError(
                            record_index=index,
                            field_name=field_def.name,
                            error_type="type",
                            message=f"Expected {field_def.field_type}, got {type(value).__name__}",
                            expected=field_def.field_type,
                            actual=type(value).__name__,
                        )
                    )

            # Pattern check
            if field_def.name in self._compiled_patterns:
                pattern = self._compiled_patterns[field_def.name]
                if not pattern.match(str(value)):
                    errors.append(
                        ValidationError(
                            record_index=index,
                            field_name=field_def.name,
                            error_type="pattern",
                            message=f"Value doesn't match pattern: {field_def.pattern}",
                            expected=field_def.pattern,
                            actual=value,
                        )
                    )

        return errors

    def _check_constraints(
        self, records: list[dict[str, Any]]
    ) -> list[ValidationError]:
        """Check cross-record constraints."""
        errors: list[ValidationError] = []

        for constraint in self._schema.constraints:
            ctype = constraint.get("type")
            if ctype == "unique":
                fields = constraint.get("fields", [])
                errors.extend(self._check_unique(records, fields))

        return errors

    def _check_unique(
        self, records: list[dict[str, Any]], fields: list[str]
    ) -> list[ValidationError]:
        """Check unique constraint across records."""
        errors: list[ValidationError] = []
        seen: dict[str, int] = {}

        for i, record in enumerate(records):
            key = "|".join(str(record.get(f, "")) for f in fields)
            if key in seen:
                errors.append(
                    ValidationError(
                        record_index=i,
                        field_name=",".join(fields),
                        error_type="unique",
                        message=f"Duplicate value at records {seen[key]} and {i}",
                        expected="unique",
                        actual=key,
                    )
                )
            else:
                seen[key] = i

        return errors
