"""Tests for the data processing pipeline.

This test module provides comprehensive tests for the DataProcessor
and Pipeline classes. Tests cover basic processing, schema validation,
transforms, error handling, and pipeline orchestration.

Test Organization
-----------------
Tests are organized by component:

1. **DataProcessor Tests**: Core processing logic
   - process_batch with valid records
   - process_batch with invalid records
   - Schema validation
   - Field transforms
   - Error handling modes
   - Deduplication
   - Input/output format handling

2. **Pipeline Tests**: Multi-stage orchestration
   - Sequential execution
   - Stage dependencies
   - Error propagation
   - Pipeline validation

3. **Integration Tests**: End-to-end scenarios
   - CSV input -> process -> JSON output
   - Multi-stage pipeline with validation
   - Error recovery and reporting

Fixtures
--------
Test fixtures are defined as module-level constants to avoid
repetition. Each fixture represents a realistic data scenario.

Coverage Goals
--------------
- Line coverage: >90% for DataProcessor
- Branch coverage: >85% for Pipeline
- All error paths tested
- All configuration options tested

Change History
--------------
- v1.0: Basic DataProcessor tests
- v1.1: Added Pipeline tests
- v1.2: Added integration tests
- v1.3: Added error handling tests
- v1.4: Added dedup and transform tests
- v1.5: Added metrics verification tests
"""

from __future__ import annotations

import json
import pytest
from typing import Any


# ── Test Fixtures ──────────────────────────────────────────────────────────

VALID_RECORDS = [
    {"name": "Alice Johnson", "email": "alice@example.com", "age": "30", "city": "Portland"},
    {"name": "Bob Smith", "email": "bob@example.com", "age": "25", "city": "Seattle"},
    {"name": "Charlie Brown", "email": "charlie@example.com", "age": "35", "city": "Denver"},
    {"name": "Diana Prince", "email": "diana@example.com", "age": "28", "city": "Austin"},
    {"name": "Eve Wilson", "email": "eve@example.com", "age": "42", "city": "Chicago"},
]

INVALID_RECORDS = [
    {"name": "", "email": "invalid", "age": "abc", "city": ""},
    {"name": "Test", "email": "test@example.com", "age": "-5", "city": "Nowhere"},
    {"name": "A" * 500, "email": "", "age": "999", "city": "x"},
]

DUPLICATE_RECORDS = [
    {"name": "Alice", "email": "alice@example.com", "age": "30"},
    {"name": "Alice", "email": "alice@example.com", "age": "30"},
    {"name": "Bob", "email": "bob@example.com", "age": "25"},
    {"name": "Alice", "email": "alice@example.com", "age": "30"},
]

CSV_SAMPLE = """name,email,age,city
Alice,alice@example.com,30,Portland
Bob,bob@example.com,25,Seattle
Charlie,charlie@example.com,35,Denver
"""

JSON_SAMPLE = [
    {"name": "Alice", "email": "alice@example.com", "age": 30},
    {"name": "Bob", "email": "bob@example.com", "age": 25},
]


# ── DataProcessor Tests ───────────────────────────────────────────────────


class TestDataProcessorBasic:
    """Basic DataProcessor functionality tests."""

    def test_process_empty_batch(self):
        """Processing an empty batch should return empty results.

        The DataProcessor.process_batch method should handle empty
        input gracefully without errors.
        """
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        result = processor.process_batch([])
        assert result == []
        assert processor.get_metrics().total_records == 0

    def test_process_valid_records(self):
        """Valid records should pass through processing unchanged.

        When no schema validation is configured, the DataProcessor
        should pass all records through the pre-processing stage
        and return them.
        """
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        result = processor.process_batch(VALID_RECORDS)
        assert len(result) == len(VALID_RECORDS)

    def test_process_with_whitespace_stripping(self):
        """DataProcessor should strip whitespace by default."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor, ProcessorConfig
        config = ProcessorConfig(strip_whitespace=True)
        processor = DataProcessor(config)
        records = [{"name": "  Alice  ", "city": " Portland "}]
        result = processor.process_batch(records)
        assert result[0]["name"] == "Alice"
        assert result[0]["city"] == "Portland"

    def test_process_null_normalization(self):
        """DataProcessor should convert null string values to None."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor, ProcessorConfig
        config = ProcessorConfig(null_values=["", "null", "N/A"])
        processor = DataProcessor(config)
        records = [{"name": "Alice", "city": "N/A", "state": "null"}]
        result = processor.process_batch(records)
        assert result[0]["name"] == "Alice"
        assert result[0]["city"] is None
        assert result[0]["state"] is None


class TestDataProcessorSchema:
    """Schema validation tests for DataProcessor."""

    def test_required_field_validation(self):
        """Missing required fields should generate errors.

        The DataProcessor should skip records where required
        fields are missing or empty.
        """
        from scale_multi_refactor.src.core.data_processor import (
            DataProcessor, ProcessorConfig, FieldSchema, ErrorMode,
        )
        config = ProcessorConfig(
            schema=[FieldSchema(name="email", required=True)],
            error_mode=ErrorMode.LENIENT,
        )
        processor = DataProcessor(config)
        records = [
            {"email": "alice@example.com"},
            {"email": ""},
            {"email": "bob@example.com"},
        ]
        result = processor.process_batch(records)
        assert len(result) == 2
        assert len(processor.get_errors()) == 1

    def test_type_validation(self):
        """Invalid types should generate errors."""
        from scale_multi_refactor.src.core.data_processor import (
            DataProcessor, ProcessorConfig, FieldSchema, ErrorMode,
        )
        config = ProcessorConfig(
            schema=[FieldSchema(name="age", field_type="int", required=True)],
            error_mode=ErrorMode.LENIENT,
        )
        processor = DataProcessor(config)
        records = [
            {"age": "30"},
            {"age": "abc"},
            {"age": "25"},
        ]
        result = processor.process_batch(records)
        assert len(result) == 2


class TestDataProcessorDedup:
    """Deduplication tests for DataProcessor."""

    def test_dedup_removes_duplicates(self):
        """Deduplication should remove records with matching key fields."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor, ProcessorConfig
        config = ProcessorConfig(dedup_fields=["email"])
        processor = DataProcessor(config)
        result = processor.process_batch(DUPLICATE_RECORDS)
        assert len(result) == 2  # Alice and Bob

    def test_dedup_preserves_first_occurrence(self):
        """The first occurrence of each unique key should be kept."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor, ProcessorConfig
        config = ProcessorConfig(dedup_fields=["name", "email"])
        processor = DataProcessor(config)
        result = processor.process_batch(DUPLICATE_RECORDS)
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"


class TestDataProcessorMetrics:
    """Metrics tracking tests for DataProcessor."""

    def test_metrics_track_record_counts(self):
        """Metrics should track total, processed, and skipped counts."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        processor.process_batch(VALID_RECORDS)
        metrics = processor.get_metrics()
        assert metrics.total_records == 5
        assert metrics.processed_records == 5
        assert metrics.skipped_records == 0

    def test_metrics_track_duration(self):
        """Metrics should include processing duration."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        processor.process_batch(VALID_RECORDS)
        metrics = processor.get_metrics()
        assert metrics.duration >= 0

    def test_metrics_calculate_throughput(self):
        """Metrics should calculate records per second."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        processor.process_batch(VALID_RECORDS * 100)
        metrics = processor.get_metrics()
        assert metrics.throughput > 0


class TestDataProcessorTransforms:
    """Transform tests for DataProcessor."""

    def test_lowercase_transform(self):
        """Lowercase transform should convert string values."""
        from scale_multi_refactor.src.core.data_processor import (
            DataProcessor, ProcessorConfig, FieldSchema,
        )
        config = ProcessorConfig(
            schema=[FieldSchema(name="name", transform="lowercase")],
        )
        processor = DataProcessor(config)
        records = [{"name": "ALICE JOHNSON"}]
        result = processor.process_batch(records)
        assert result[0]["name"] == "alice johnson"

    def test_email_normalization(self):
        """Email normalization should lowercase and strip."""
        from scale_multi_refactor.src.core.data_processor import (
            DataProcessor, ProcessorConfig, FieldSchema,
        )
        config = ProcessorConfig(
            schema=[FieldSchema(name="email", transform="normalize_email")],
        )
        processor = DataProcessor(config)
        records = [{"email": "  Alice@Example.COM  "}]
        result = processor.process_batch(records)
        assert result[0]["email"] == "alice@example.com"


class TestDataProcessorIO:
    """Input/output format tests for DataProcessor."""

    def test_read_csv(self):
        """DataProcessor should parse CSV content."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        records = processor.read_csv(CSV_SAMPLE)
        assert len(records) == 3
        assert records[0]["name"] == "Alice"

    def test_read_json(self):
        """DataProcessor should parse JSON content."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        records = processor.read_json(json.dumps(JSON_SAMPLE))
        assert len(records) == 2

    def test_write_json(self):
        """DataProcessor should serialize records to JSON."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        processor = DataProcessor()
        output = processor.write_json(VALID_RECORDS)
        parsed = json.loads(output)
        assert len(parsed) == len(VALID_RECORDS)


# ── Pipeline Tests ─────────────────────────────────────────────────────────


class TestPipeline:
    """Pipeline orchestration tests."""

    def test_single_stage_pipeline(self):
        """A pipeline with one stage should process records correctly.

        The Pipeline uses DataProcessor.process_batch internally
        for each stage.
        """
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        from scale_multi_refactor.src.core.pipeline import Pipeline
        pipeline = Pipeline("test")
        pipeline.add_stage("process", DataProcessor())
        result = pipeline.execute(VALID_RECORDS)
        assert result.success
        assert result.records_out == len(VALID_RECORDS)

    def test_multi_stage_pipeline(self):
        """A pipeline with multiple stages should chain processing."""
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        from scale_multi_refactor.src.core.pipeline import Pipeline
        pipeline = Pipeline("multi")
        pipeline.add_stage("stage1", DataProcessor())
        pipeline.add_stage("stage2", DataProcessor(), depends_on=["stage1"])
        result = pipeline.execute(VALID_RECORDS)
        assert result.success
        assert len(result.stage_results) == 2

    def test_pipeline_validation(self):
        """Pipeline validation should catch missing dependencies."""
        from scale_multi_refactor.src.core.pipeline import Pipeline
        from scale_multi_refactor.src.core.data_processor import DataProcessor
        pipeline = Pipeline("invalid")
        pipeline.add_stage("stage1", DataProcessor(), depends_on=["nonexistent"])
        errors = pipeline.validate()
        assert len(errors) > 0

    def test_empty_pipeline_validation(self):
        """An empty pipeline should fail validation."""
        from scale_multi_refactor.src.core.pipeline import Pipeline
        pipeline = Pipeline("empty")
        errors = pipeline.validate()
        assert any("no stages" in e.lower() for e in errors)
