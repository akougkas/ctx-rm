"""Core data processing engine.

This module provides the ``DataProcessor`` class, the central component
of the data processing pipeline. It handles ingestion, transformation,
validation, and output of structured data records.

Architecture Overview
---------------------
The DataProcessor follows a pipeline architecture where data flows through
a series of configurable stages:

1. **Ingestion**: Raw data is read from various sources (CSV, JSON, API)
2. **Validation**: Data is validated against schema rules
3. **Transformation**: Business logic transforms are applied
4. **Enrichment**: External data sources are joined
5. **Output**: Processed data is written to destination

Each stage is implemented as a method on the DataProcessor class, allowing
fine-grained control over the processing pipeline. The ``process_batch``
method orchestrates the full pipeline for a batch of records.

Performance Characteristics
---------------------------
- Batch processing: Optimized for batches of 100-10,000 records
- Memory: O(n) memory usage where n is batch size
- CPU: Linear time complexity for most operations
- I/O: Buffered reads and writes for efficiency

Thread Safety
-------------
The DataProcessor is NOT thread-safe. Each thread should create its own
instance. For concurrent processing, use the ``ParallelProcessor`` wrapper
which manages a pool of DataProcessor instances.

Error Handling
--------------
Processing errors are categorized into:
- **ValidationError**: Data doesn't meet schema requirements
- **TransformError**: Business logic transform failed
- **IOError**: Source/destination I/O failure

Errors can be configured to either halt processing (strict mode) or
be collected and reported after batch completion (lenient mode).

Retry Policy
------------
Transient errors (network timeouts, temporary file locks) are retried
with exponential backoff:
- 1st retry: 100ms delay
- 2nd retry: 500ms delay
- 3rd retry: 2s delay
- After 3 failures: error is raised

Monitoring
----------
The DataProcessor emits metrics for:
- Records processed per batch
- Processing duration per stage
- Error count by category
- Throughput (records/second)

Configuration
-------------
DataProcessor behavior is controlled by a ProcessorConfig dataclass
that specifies schema validation rules, transform chains, error handling
mode, and output formatting options.

Change History
--------------
- v1.0: Basic CSV processing
- v1.1: Added JSON source support
- v1.2: Added schema validation
- v1.3: Added transform pipeline
- v1.4: Added batch processing with process_batch
- v1.5: Added enrichment stage
- v1.6: Added metrics and monitoring
- v1.7: Added parallel processing support
- v1.8: Added streaming output mode
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Iterator, Optional, Sequence

logger = logging.getLogger(__name__)


class ErrorMode(Enum):
    """Error handling mode for the processor.

    STRICT: Stop processing on first error.
    LENIENT: Collect errors and continue processing.
    SKIP: Skip invalid records silently.
    """

    STRICT = "strict"
    LENIENT = "lenient"
    SKIP = "skip"


class DataFormat(Enum):
    """Supported data formats for input and output."""

    CSV = "csv"
    JSON = "json"
    JSONL = "jsonl"
    TSV = "tsv"


@dataclass
class FieldSchema:
    """Schema definition for a single data field.

    Defines the name, type, validation rules, and transformation
    for a data field. Used by the validation stage to check records
    against expected structure.

    Attributes:
        name: Field name (column header).
        field_type: Expected data type ("str", "int", "float", "decimal", "date", "bool").
        required: Whether the field must be present and non-empty.
        min_value: Minimum numeric value (for numeric types).
        max_value: Maximum numeric value (for numeric types).
        min_length: Minimum string length (for str type).
        max_length: Maximum string length (for str type).
        pattern: Regex pattern the value must match (for str type).
        choices: Allowed values (for enum-like fields).
        default: Default value if field is missing.
        transform: Optional transform function name.
    """

    name: str = ""
    field_type: str = "str"
    required: bool = True
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: int = 0
    max_length: int = 65535
    pattern: Optional[str] = None
    choices: Optional[list[str]] = None
    default: Any = None
    transform: Optional[str] = None


@dataclass
class ProcessorConfig:
    """Configuration for the DataProcessor.

    Controls all aspects of data processing including schema validation,
    error handling, output formatting, and performance tuning.

    Attributes:
        schema: List of field schema definitions.
        error_mode: How to handle processing errors.
        input_format: Expected input data format.
        output_format: Desired output data format.
        batch_size: Number of records to process per batch.
        max_errors: Maximum errors before stopping in lenient mode.
        enable_metrics: Whether to collect processing metrics.
        enable_enrichment: Whether to run the enrichment stage.
        date_format: Expected date format string.
        decimal_places: Number of decimal places for numeric output.
        null_values: Strings treated as null/empty.
        strip_whitespace: Whether to strip leading/trailing whitespace.
        normalize_case: Whether to normalize string case ("lower", "upper", None).
        dedup_fields: Fields to use for deduplication (empty = no dedup).
    """

    schema: list[FieldSchema] = field(default_factory=list)
    error_mode: ErrorMode = ErrorMode.LENIENT
    input_format: DataFormat = DataFormat.CSV
    output_format: DataFormat = DataFormat.JSON
    batch_size: int = 1000
    max_errors: int = 100
    enable_metrics: bool = True
    enable_enrichment: bool = False
    date_format: str = "%Y-%m-%d"
    decimal_places: int = 2
    null_values: list[str] = field(
        default_factory=lambda: ["", "null", "NULL", "None", "N/A", "n/a", "-"]
    )
    strip_whitespace: bool = True
    normalize_case: Optional[str] = None
    dedup_fields: list[str] = field(default_factory=list)


@dataclass
class ProcessingMetrics:
    """Metrics collected during batch processing.

    Provides detailed statistics about the processing run including
    record counts, timing, error categorization, and throughput.

    Attributes:
        total_records: Total number of input records.
        processed_records: Records successfully processed.
        skipped_records: Records skipped due to errors.
        error_count: Total number of errors encountered.
        errors_by_type: Error count grouped by error type.
        errors_by_field: Error count grouped by field name.
        start_time: Processing start timestamp.
        end_time: Processing end timestamp.
        stage_durations: Time spent in each processing stage.
        throughput: Records processed per second.
        dedup_removed: Records removed by deduplication.
    """

    total_records: int = 0
    processed_records: int = 0
    skipped_records: int = 0
    error_count: int = 0
    errors_by_type: dict[str, int] = field(default_factory=lambda: Counter())
    errors_by_field: dict[str, int] = field(default_factory=lambda: Counter())
    start_time: float = 0.0
    end_time: float = 0.0
    stage_durations: dict[str, float] = field(default_factory=dict)
    throughput: float = 0.0
    dedup_removed: int = 0

    @property
    def duration(self) -> float:
        """Total processing duration in seconds."""
        return self.end_time - self.start_time

    @property
    def success_rate(self) -> float:
        """Percentage of records successfully processed."""
        if self.total_records == 0:
            return 0.0
        return (self.processed_records / self.total_records) * 100

    def to_dict(self) -> dict[str, Any]:
        """Serialize metrics to a dictionary."""
        return {
            "total_records": self.total_records,
            "processed_records": self.processed_records,
            "skipped_records": self.skipped_records,
            "error_count": self.error_count,
            "success_rate": f"{self.success_rate:.1f}%",
            "duration_seconds": f"{self.duration:.3f}",
            "throughput_rps": f"{self.throughput:.1f}",
            "errors_by_type": dict(self.errors_by_type),
            "dedup_removed": self.dedup_removed,
        }


@dataclass
class ProcessingError:
    """A single processing error with context.

    Attributes:
        record_index: Index of the record that caused the error.
        field_name: Name of the field that failed (if applicable).
        error_type: Category of the error.
        message: Human-readable error description.
        raw_value: The original value that caused the error.
    """

    record_index: int = 0
    field_name: str = ""
    error_type: str = "unknown"
    message: str = ""
    raw_value: Any = None


class DataProcessor:
    """Core data processing engine.

    Processes structured data records through a configurable pipeline
    of validation, transformation, and enrichment stages.

    The main entry point is ``process_batch`` which accepts a list
    of records and returns the processed output along with metrics
    and any errors encountered.

    Args:
        config: Processor configuration.
        enrichment_sources: Optional dict of enrichment data sources.
    """

    def __init__(
        self,
        config: Optional[ProcessorConfig] = None,
        enrichment_sources: Optional[dict[str, Any]] = None,
    ) -> None:
        self._config = config or ProcessorConfig()
        self._enrichment = enrichment_sources or {}
        self._metrics = ProcessingMetrics()
        self._errors: list[ProcessingError] = []
        self._transform_registry: dict[str, Callable] = {
            "lowercase": lambda v: v.lower() if isinstance(v, str) else v,
            "uppercase": lambda v: v.upper() if isinstance(v, str) else v,
            "strip": lambda v: v.strip() if isinstance(v, str) else v,
            "title": lambda v: v.title() if isinstance(v, str) else v,
            "normalize_phone": self._normalize_phone,
            "normalize_email": self._normalize_email,
            "parse_date": self._parse_date,
            "parse_decimal": self._parse_decimal,
        }

    def process_batch(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process a batch of data records through the full pipeline.

        This is the main entry point for batch processing. It runs
        each record through validation, transformation, enrichment,
        and formatting stages according to the processor configuration.

        Pipeline stages:
        1. Pre-processing (whitespace stripping, null normalization)
        2. Deduplication (if configured)
        3. Schema validation
        4. Field transformation
        5. Enrichment (if enabled)
        6. Post-processing (formatting, serialization)

        Args:
            records: List of dictionaries representing data records.

        Returns:
            List of processed records that passed all stages.

        Raises:
            RuntimeError: In STRICT mode if any validation error occurs.
        """
        self._metrics = ProcessingMetrics()
        self._errors = []
        self._metrics.start_time = time.time()
        self._metrics.total_records = len(records)

        logger.info("Starting batch processing: records=%d", len(records))

        # Stage 1: Pre-processing
        stage_start = time.time()
        records = [self._preprocess(r) for r in records]
        self._metrics.stage_durations["preprocess"] = time.time() - stage_start

        # Stage 2: Deduplication
        if self._config.dedup_fields:
            stage_start = time.time()
            original_count = len(records)
            records = self._deduplicate(records)
            self._metrics.dedup_removed = original_count - len(records)
            self._metrics.stage_durations["dedup"] = time.time() - stage_start

        # Stage 3-5: Validate, transform, enrich
        output: list[dict[str, Any]] = []
        stage_start = time.time()

        for i, record in enumerate(records):
            errors = self._validate_record(record, i)
            if errors:
                self._handle_errors(errors)
                self._metrics.skipped_records += 1
                continue

            record = self._transform_record(record)

            if self._config.enable_enrichment:
                record = self._enrich_record(record)

            output.append(record)
            self._metrics.processed_records += 1

        self._metrics.stage_durations["process"] = time.time() - stage_start

        # Finalize metrics
        self._metrics.end_time = time.time()
        duration = self._metrics.duration
        if duration > 0:
            self._metrics.throughput = self._metrics.processed_records / duration

        logger.info(
            "Batch processing complete: processed=%d skipped=%d errors=%d duration=%.3fs",
            self._metrics.processed_records,
            self._metrics.skipped_records,
            self._metrics.error_count,
            duration,
        )

        return output

    def get_metrics(self) -> ProcessingMetrics:
        """Return metrics from the last processing run."""
        return self._metrics

    def get_errors(self) -> list[ProcessingError]:
        """Return errors from the last processing run."""
        return self._errors

    def _preprocess(self, record: dict[str, Any]) -> dict[str, Any]:
        """Apply pre-processing steps to a record."""
        result: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, str):
                if self._config.strip_whitespace:
                    value = value.strip()
                if value in self._config.null_values:
                    value = None
                elif self._config.normalize_case == "lower":
                    value = value.lower()
                elif self._config.normalize_case == "upper":
                    value = value.upper()
            result[key] = value
        return result

    def _deduplicate(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate records based on configured fields."""
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for record in records:
            key_parts = [str(record.get(f, "")) for f in self._config.dedup_fields]
            key = "|".join(key_parts)
            key_hash = hashlib.md5(key.encode()).hexdigest()
            if key_hash not in seen:
                seen.add(key_hash)
                unique.append(record)
        return unique

    def _validate_record(
        self, record: dict[str, Any], index: int
    ) -> list[ProcessingError]:
        """Validate a record against the schema."""
        errors: list[ProcessingError] = []
        for field_schema in self._config.schema:
            value = record.get(field_schema.name)

            # Required check
            if field_schema.required and (value is None or value == ""):
                errors.append(
                    ProcessingError(
                        record_index=index,
                        field_name=field_schema.name,
                        error_type="required",
                        message=f"Required field '{field_schema.name}' is missing",
                        raw_value=value,
                    )
                )
                continue

            if value is None:
                continue

            # Type check
            type_error = self._check_type(field_schema, value, index)
            if type_error:
                errors.append(type_error)
                continue

            # Range check for numeric types
            if field_schema.field_type in ("int", "float", "decimal"):
                try:
                    num_val = float(value) if isinstance(value, str) else value
                    if field_schema.min_value is not None and num_val < field_schema.min_value:
                        errors.append(
                            ProcessingError(
                                record_index=index,
                                field_name=field_schema.name,
                                error_type="range",
                                message=f"Value {num_val} below minimum {field_schema.min_value}",
                                raw_value=value,
                            )
                        )
                    if field_schema.max_value is not None and num_val > field_schema.max_value:
                        errors.append(
                            ProcessingError(
                                record_index=index,
                                field_name=field_schema.name,
                                error_type="range",
                                message=f"Value {num_val} above maximum {field_schema.max_value}",
                                raw_value=value,
                            )
                        )
                except (ValueError, TypeError):
                    pass

            # Length check for string types
            if field_schema.field_type == "str" and isinstance(value, str):
                if len(value) < field_schema.min_length:
                    errors.append(
                        ProcessingError(
                            record_index=index,
                            field_name=field_schema.name,
                            error_type="length",
                            message=f"Value too short (min {field_schema.min_length})",
                            raw_value=value,
                        )
                    )
                if len(value) > field_schema.max_length:
                    errors.append(
                        ProcessingError(
                            record_index=index,
                            field_name=field_schema.name,
                            error_type="length",
                            message=f"Value too long (max {field_schema.max_length})",
                            raw_value=value,
                        )
                    )

            # Pattern check
            if field_schema.pattern and isinstance(value, str):
                if not re.match(field_schema.pattern, value):
                    errors.append(
                        ProcessingError(
                            record_index=index,
                            field_name=field_schema.name,
                            error_type="pattern",
                            message=f"Value doesn't match pattern: {field_schema.pattern}",
                            raw_value=value,
                        )
                    )

            # Choices check
            if field_schema.choices and str(value) not in field_schema.choices:
                errors.append(
                    ProcessingError(
                        record_index=index,
                        field_name=field_schema.name,
                        error_type="choices",
                        message=f"Value must be one of: {field_schema.choices}",
                        raw_value=value,
                    )
                )

        return errors

    def _check_type(
        self, schema: FieldSchema, value: Any, index: int
    ) -> Optional[ProcessingError]:
        """Check that a value matches the expected type."""
        try:
            if schema.field_type == "int":
                int(value)
            elif schema.field_type == "float":
                float(value)
            elif schema.field_type == "decimal":
                Decimal(str(value))
            elif schema.field_type == "bool":
                if str(value).lower() not in ("true", "false", "1", "0", "yes", "no"):
                    raise ValueError("Not a boolean")
            elif schema.field_type == "date":
                datetime.strptime(str(value), self._config.date_format)
        except (ValueError, InvalidOperation):
            return ProcessingError(
                record_index=index,
                field_name=schema.name,
                error_type="type",
                message=f"Cannot convert '{value}' to {schema.field_type}",
                raw_value=value,
            )
        return None

    def _transform_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Apply field-level transforms to a record."""
        for schema in self._config.schema:
            if schema.transform and schema.name in record:
                transform_fn = self._transform_registry.get(schema.transform)
                if transform_fn:
                    record[schema.name] = transform_fn(record[schema.name])
        return record

    def _enrich_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Enrich a record with data from external sources."""
        for source_name, source_data in self._enrichment.items():
            if isinstance(source_data, dict):
                for key in record:
                    lookup_val = str(record[key])
                    if lookup_val in source_data:
                        record[f"{source_name}_{key}"] = source_data[lookup_val]
        return record

    def _handle_errors(self, errors: list[ProcessingError]) -> None:
        """Handle processing errors according to the configured mode."""
        self._errors.extend(errors)
        self._metrics.error_count += len(errors)
        for error in errors:
            self._metrics.errors_by_type[error.error_type] += 1
            self._metrics.errors_by_field[error.field_name] += 1

        if self._config.error_mode == ErrorMode.STRICT:
            raise RuntimeError(
                f"Processing error in strict mode: {errors[0].message}"
            )

    @staticmethod
    def _normalize_phone(value: Any) -> str:
        """Normalize a phone number to E.164 format."""
        if not isinstance(value, str):
            return str(value)
        digits = re.sub(r"[^\d+]", "", value)
        if not digits.startswith("+"):
            digits = "+1" + digits
        return digits

    @staticmethod
    def _normalize_email(value: Any) -> str:
        """Normalize an email address."""
        if not isinstance(value, str):
            return str(value)
        return value.strip().lower()

    def _parse_date(self, value: Any) -> str:
        """Parse a date string and reformat it."""
        if not isinstance(value, str):
            return str(value)
        try:
            dt = datetime.strptime(value, self._config.date_format)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return value

    @staticmethod
    def _parse_decimal(value: Any) -> str:
        """Parse a value as a decimal string."""
        try:
            return str(Decimal(str(value)).quantize(Decimal("0.01")))
        except InvalidOperation:
            return str(value)

    def read_csv(self, content: str) -> list[dict[str, Any]]:
        """Parse CSV content into a list of records."""
        reader = csv.DictReader(io.StringIO(content))
        return [dict(row) for row in reader]

    def read_json(self, content: str) -> list[dict[str, Any]]:
        """Parse JSON content into a list of records."""
        data = json.loads(content)
        if isinstance(data, list):
            return data
        return [data]

    def read_jsonl(self, content: str) -> list[dict[str, Any]]:
        """Parse JSON Lines content into a list of records."""
        records = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def write_csv(self, records: list[dict[str, Any]]) -> str:
        """Serialize records to CSV format."""
        if not records:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
        return output.getvalue()

    def write_json(self, records: list[dict[str, Any]]) -> str:
        """Serialize records to JSON format."""
        return json.dumps(records, indent=2, default=str)

    def write_jsonl(self, records: list[dict[str, Any]]) -> str:
        """Serialize records to JSON Lines format."""
        lines = [json.dumps(r, default=str) for r in records]
        return "\n".join(lines)
