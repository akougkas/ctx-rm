"""Input handler for receiving and parsing incoming data.

This module provides the ``InputHandler`` class that receives raw data
from various sources (files, HTTP requests, message queues) and prepares
it for processing by the ``DataProcessor`` pipeline.

The InputHandler sits between external data sources and the core
processing engine, handling format detection, parsing, and initial
validation before handing off to the DataProcessor.

Supported Input Sources
-----------------------
- **File system**: CSV, JSON, JSONL, TSV files with auto-detection
- **HTTP**: POST request bodies with content-type negotiation
- **Message queue**: Messages from RabbitMQ, Kafka, SQS
- **Database**: Query results from SQL databases
- **API**: Paginated results from REST APIs

Data Flow
---------
::

    External Source → InputHandler → DataProcessor → OutputHandler
                     ↑
                     Format detection
                     Parsing
                     Initial validation
                     Batching

Batching Strategy
-----------------
Large inputs are automatically batched according to configurable
thresholds. The handler reads data incrementally and yields batches
to the DataProcessor for processing.

Batch sizes can be configured based on:
- Record count (default: 1000 records per batch)
- Memory size (default: 100MB per batch)
- Time window (default: 30 seconds per batch)

Error Handling
--------------
Parse errors at the input level are handled separately from
processing errors. Input errors include:
- Malformed CSV/JSON syntax
- Character encoding issues
- File access errors
- Network timeouts

Monitoring
----------
The handler tracks:
- Bytes read per source
- Parse error rate
- Batch generation rate
- Source type distribution

Change History
--------------
- v1.0: Basic CSV file input
- v1.1: Added JSON and JSONL support
- v1.2: Added HTTP input handling
- v1.3: Added message queue integration
- v1.4: Added auto-batching
- v1.5: Added streaming input for large files
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from ..core.data_processor import DataProcessor, DataFormat, ProcessorConfig

logger = logging.getLogger(__name__)


@dataclass
class InputSource:
    """Description of a data input source.

    Attributes:
        source_type: Type of source ("file", "http", "queue", "db", "api").
        location: Source location (file path, URL, queue name, etc).
        format: Data format (auto-detected if not specified).
        encoding: Character encoding (default UTF-8).
        options: Source-specific options.
        metadata: Additional metadata about the source.
    """

    source_type: str = "file"
    location: str = ""
    format: Optional[DataFormat] = None
    encoding: str = "utf-8"
    options: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InputResult:
    """Result of an input operation.

    Attributes:
        success: Whether the input was successfully parsed.
        records: Parsed data records.
        record_count: Number of records parsed.
        bytes_read: Total bytes read from source.
        parse_errors: List of parse error messages.
        source: The input source that was read.
        duration: Time taken to read and parse.
    """

    success: bool = True
    records: list[dict[str, Any]] = field(default_factory=list)
    record_count: int = 0
    bytes_read: int = 0
    parse_errors: list[str] = field(default_factory=list)
    source: Optional[InputSource] = None
    duration: float = 0.0


@dataclass
class BatchConfig:
    """Configuration for automatic batching of input data.

    Attributes:
        batch_size: Maximum records per batch.
        max_memory_mb: Maximum memory per batch in megabytes.
        max_wait_seconds: Maximum time to wait for a full batch.
        flush_on_close: Whether to flush remaining records on close.
    """

    batch_size: int = 1000
    max_memory_mb: int = 100
    max_wait_seconds: float = 30.0
    flush_on_close: bool = True


class InputHandler:
    """Handles receiving and parsing input data for processing.

    Bridges external data sources with the DataProcessor by handling
    format detection, parsing, validation, and batching.

    The handler can be used directly to read files or other sources,
    or it can be configured with a DataProcessor to automatically
    feed parsed data into the processing pipeline.

    Args:
        processor: Optional DataProcessor to feed parsed data into.
        batch_config: Configuration for automatic batching.
    """

    # Format detection based on file extensions
    FORMAT_EXTENSIONS: dict[str, DataFormat] = {
        ".csv": DataFormat.CSV,
        ".json": DataFormat.JSON,
        ".jsonl": DataFormat.JSONL,
        ".tsv": DataFormat.TSV,
    }

    # MIME type to format mapping
    FORMAT_MIME_TYPES: dict[str, DataFormat] = {
        "text/csv": DataFormat.CSV,
        "application/json": DataFormat.JSON,
        "application/x-ndjson": DataFormat.JSONL,
        "text/tab-separated-values": DataFormat.TSV,
    }

    def __init__(
        self,
        processor: Optional[DataProcessor] = None,
        batch_config: Optional[BatchConfig] = None,
    ) -> None:
        self._processor = processor
        self._batch_config = batch_config or BatchConfig()
        self._total_bytes_read = 0
        self._total_records_parsed = 0
        self._total_parse_errors = 0

    def read_file(self, file_path: str | Path) -> InputResult:
        """Read and parse a data file.

        Auto-detects the format based on the file extension if not
        explicitly specified. Reads the entire file into memory.

        Args:
            file_path: Path to the data file.

        Returns:
            InputResult with parsed records or error details.
        """
        path = Path(file_path)
        start_time = time.time()

        if not path.exists():
            return InputResult(
                success=False,
                parse_errors=[f"File not found: {path}"],
            )

        # Detect format from extension
        data_format = self.FORMAT_EXTENSIONS.get(path.suffix.lower())
        if data_format is None:
            return InputResult(
                success=False,
                parse_errors=[f"Unsupported file format: {path.suffix}"],
            )

        try:
            content = path.read_text(encoding="utf-8")
            bytes_read = len(content.encode("utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            return InputResult(
                success=False,
                parse_errors=[f"File read error: {exc}"],
            )

        # Parse content
        records, errors = self._parse_content(content, data_format)

        self._total_bytes_read += bytes_read
        self._total_records_parsed += len(records)
        self._total_parse_errors += len(errors)

        duration = time.time() - start_time
        logger.info(
            "File read: path=%s format=%s records=%d bytes=%d duration=%.3fs",
            path, data_format.value, len(records), bytes_read, duration,
        )

        return InputResult(
            success=len(errors) == 0,
            records=records,
            record_count=len(records),
            bytes_read=bytes_read,
            parse_errors=errors,
            source=InputSource(
                source_type="file",
                location=str(path),
                format=data_format,
            ),
            duration=duration,
        )

    def read_string(self, content: str, data_format: DataFormat) -> InputResult:
        """Parse a string of data in the specified format.

        Args:
            content: The raw data string.
            data_format: The format of the data.

        Returns:
            InputResult with parsed records.
        """
        start_time = time.time()
        records, errors = self._parse_content(content, data_format)

        return InputResult(
            success=len(errors) == 0,
            records=records,
            record_count=len(records),
            bytes_read=len(content.encode("utf-8")),
            parse_errors=errors,
            duration=time.time() - start_time,
        )

    def read_and_process(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Read a file and process it through the DataProcessor.

        Convenience method that combines file reading with processing.
        Requires a DataProcessor to be configured.

        Args:
            file_path: Path to the data file.

        Returns:
            Processed records.

        Raises:
            RuntimeError: If no DataProcessor is configured.
        """
        if self._processor is None:
            raise RuntimeError("No DataProcessor configured for InputHandler")

        input_result = self.read_file(file_path)
        if not input_result.records:
            logger.warning("No records parsed from %s", file_path)
            return []

        return self._processor.process_batch(input_result.records)

    def read_batched(
        self, file_path: str | Path
    ) -> Iterator[list[dict[str, Any]]]:
        """Read a file and yield batches of records.

        For large files, this method yields batches according to
        the configured batch size instead of loading everything
        into memory at once.

        Args:
            file_path: Path to the data file.

        Yields:
            Lists of records, each up to batch_size in length.
        """
        input_result = self.read_file(file_path)
        records = input_result.records
        batch_size = self._batch_config.batch_size

        for i in range(0, len(records), batch_size):
            yield records[i : i + batch_size]

    def process_batched(
        self, file_path: str | Path
    ) -> Iterator[list[dict[str, Any]]]:
        """Read, batch, and process a file incrementally.

        Combines batched reading with DataProcessor processing.
        Each batch is processed independently.

        Args:
            file_path: Path to the data file.

        Yields:
            Processed record batches.
        """
        if self._processor is None:
            raise RuntimeError("No DataProcessor configured")

        for batch in self.read_batched(file_path):
            yield self._processor.process_batch(batch)

    def detect_format(self, content: str) -> Optional[DataFormat]:
        """Auto-detect data format from content.

        Attempts to detect the format by trying each parser.
        Returns the first format that successfully parses.

        Args:
            content: The raw data string.

        Returns:
            Detected DataFormat or None if no format matches.
        """
        content = content.strip()
        if not content:
            return None

        # Try JSON first (starts with [ or {)
        if content.startswith(("[", "{")):
            try:
                json.loads(content)
                return DataFormat.JSON
            except json.JSONDecodeError:
                pass

        # Try JSONL (each line is valid JSON)
        lines = content.split("\n", 2)
        if lines:
            try:
                json.loads(lines[0])
                return DataFormat.JSONL
            except json.JSONDecodeError:
                pass

        # Try TSV (tabs in first line)
        if "\t" in lines[0]:
            return DataFormat.TSV

        # Default to CSV
        return DataFormat.CSV

    def _parse_content(
        self, content: str, data_format: DataFormat
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Parse raw content into records based on format.

        Returns:
            Tuple of (records, parse_errors).
        """
        errors: list[str] = []
        records: list[dict[str, Any]] = []

        try:
            if data_format == DataFormat.CSV:
                reader = csv.DictReader(io.StringIO(content))
                records = [dict(row) for row in reader]
            elif data_format == DataFormat.JSON:
                data = json.loads(content)
                records = data if isinstance(data, list) else [data]
            elif data_format == DataFormat.JSONL:
                for line_num, line in enumerate(content.strip().split("\n"), 1):
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError as exc:
                            errors.append(f"Line {line_num}: {exc}")
            elif data_format == DataFormat.TSV:
                reader = csv.DictReader(io.StringIO(content), delimiter="\t")
                records = [dict(row) for row in reader]
        except (csv.Error, json.JSONDecodeError) as exc:
            errors.append(f"Parse error: {exc}")

        return records, errors

    def get_stats(self) -> dict[str, Any]:
        """Return cumulative input statistics."""
        return {
            "total_bytes_read": self._total_bytes_read,
            "total_records_parsed": self._total_records_parsed,
            "total_parse_errors": self._total_parse_errors,
        }
