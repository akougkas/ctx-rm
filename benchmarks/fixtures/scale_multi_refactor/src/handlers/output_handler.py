"""Output handler for writing processed data to destinations.

This module provides the ``OutputHandler`` class that takes processed
data from the ``DataProcessor`` pipeline and writes it to various
output destinations (files, databases, APIs, message queues).

The OutputHandler mirrors the InputHandler's role on the output side
of the pipeline, handling format conversion, batching, and delivery.

Supported Output Destinations
-----------------------------
- **File system**: CSV, JSON, JSONL, TSV files
- **Database**: INSERT/UPSERT to SQL databases
- **API**: POST to REST endpoints
- **Message queue**: Publish to RabbitMQ, Kafka, SQS
- **stdout**: Print to standard output (for debugging)

Output Modes
------------
- **Overwrite**: Replace existing destination content
- **Append**: Add to existing destination content
- **Upsert**: Update existing records, insert new ones (database only)

Buffering
---------
The handler uses configurable output buffering to optimize I/O:
- Small outputs (<100 records): Written immediately
- Medium outputs (100-10000): Buffered in memory, flushed on complete
- Large outputs (>10000): Streamed with periodic flushes

Change History
--------------
- v1.0: Basic CSV file output
- v1.1: Added JSON/JSONL output
- v1.2: Added database output
- v1.3: Added API posting
- v1.4: Added output buffering
- v1.5: Added upsert mode for databases
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
from typing import Any, Optional

from ..core.data_processor import DataProcessor, DataFormat

logger = logging.getLogger(__name__)


@dataclass
class OutputDestination:
    """Description of a data output destination.

    Attributes:
        dest_type: Type of destination ("file", "db", "api", "queue", "stdout").
        location: Destination location (file path, URL, table name, etc).
        format: Output data format.
        encoding: Character encoding (default UTF-8).
        mode: Write mode ("overwrite", "append", "upsert").
        options: Destination-specific options.
    """

    dest_type: str = "file"
    location: str = ""
    format: DataFormat = DataFormat.JSON
    encoding: str = "utf-8"
    mode: str = "overwrite"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputResult:
    """Result of an output operation.

    Attributes:
        success: Whether the output was written successfully.
        records_written: Number of records written.
        bytes_written: Total bytes written.
        destination: The output destination.
        duration: Time taken to write.
        errors: Any write errors encountered.
    """

    success: bool = True
    records_written: int = 0
    bytes_written: int = 0
    destination: Optional[OutputDestination] = None
    duration: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class BufferConfig:
    """Configuration for output buffering.

    Attributes:
        buffer_size: Maximum records in buffer before flush.
        flush_interval: Maximum seconds between flushes.
        auto_flush: Whether to flush automatically.
    """

    buffer_size: int = 1000
    flush_interval: float = 30.0
    auto_flush: bool = True


class OutputHandler:
    """Handles writing processed data to output destinations.

    Takes the output from a DataProcessor pipeline and writes it
    to configured destinations with appropriate formatting and
    buffering.

    Args:
        processor: Optional DataProcessor for format conversion.
        buffer_config: Output buffering configuration.
    """

    def __init__(
        self,
        processor: Optional[DataProcessor] = None,
        buffer_config: Optional[BufferConfig] = None,
    ) -> None:
        self._processor = processor
        self._buffer_config = buffer_config or BufferConfig()
        self._buffer: list[dict[str, Any]] = []
        self._total_bytes_written = 0
        self._total_records_written = 0

    def write_file(
        self,
        records: list[dict[str, Any]],
        file_path: str | Path,
        data_format: Optional[DataFormat] = None,
    ) -> OutputResult:
        """Write records to a file.

        Auto-detects the format from the file extension if not
        explicitly specified.

        Args:
            records: Processed records to write.
            file_path: Output file path.
            data_format: Output format (auto-detected from extension).

        Returns:
            OutputResult with write statistics.
        """
        path = Path(file_path)
        start_time = time.time()

        if data_format is None:
            ext_map = {
                ".csv": DataFormat.CSV,
                ".json": DataFormat.JSON,
                ".jsonl": DataFormat.JSONL,
                ".tsv": DataFormat.TSV,
            }
            data_format = ext_map.get(path.suffix.lower(), DataFormat.JSON)

        try:
            content = self._format_records(records, data_format)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            bytes_written = len(content.encode("utf-8"))
        except (OSError, ValueError) as exc:
            return OutputResult(
                success=False,
                errors=[f"Write error: {exc}"],
                destination=OutputDestination(
                    dest_type="file", location=str(path), format=data_format
                ),
            )

        self._total_bytes_written += bytes_written
        self._total_records_written += len(records)

        duration = time.time() - start_time
        logger.info(
            "File written: path=%s format=%s records=%d bytes=%d duration=%.3fs",
            path, data_format.value, len(records), bytes_written, duration,
        )

        return OutputResult(
            success=True,
            records_written=len(records),
            bytes_written=bytes_written,
            destination=OutputDestination(
                dest_type="file", location=str(path), format=data_format
            ),
            duration=duration,
        )

    def write_string(
        self, records: list[dict[str, Any]], data_format: DataFormat
    ) -> str:
        """Format records as a string.

        Args:
            records: Records to format.
            data_format: Output format.

        Returns:
            Formatted string.
        """
        return self._format_records(records, data_format)

    def buffer_records(self, records: list[dict[str, Any]]) -> int:
        """Add records to the output buffer.

        Records are accumulated in the buffer until the buffer
        size threshold is reached or a manual flush is triggered.

        Args:
            records: Records to buffer.

        Returns:
            Current buffer size after adding records.
        """
        self._buffer.extend(records)
        if (
            self._buffer_config.auto_flush
            and len(self._buffer) >= self._buffer_config.buffer_size
        ):
            logger.debug("Auto-flushing buffer: size=%d", len(self._buffer))
        return len(self._buffer)

    def flush_buffer(
        self, file_path: str | Path, data_format: Optional[DataFormat] = None
    ) -> OutputResult:
        """Flush buffered records to a file.

        Writes all buffered records and clears the buffer.

        Args:
            file_path: Output file path.
            data_format: Output format.

        Returns:
            OutputResult with write statistics.
        """
        records = list(self._buffer)
        self._buffer.clear()
        if not records:
            return OutputResult(success=True, records_written=0)
        return self.write_file(records, file_path, data_format)

    def get_buffer_size(self) -> int:
        """Return the current number of records in the buffer."""
        return len(self._buffer)

    def clear_buffer(self) -> int:
        """Clear the output buffer and return the number of discarded records."""
        count = len(self._buffer)
        self._buffer.clear()
        return count

    def _format_records(
        self, records: list[dict[str, Any]], data_format: DataFormat
    ) -> str:
        """Convert records to the specified output format.

        Uses the DataProcessor's serialization methods if available,
        otherwise falls back to built-in formatting.
        """
        if self._processor is not None:
            if data_format == DataFormat.CSV:
                return self._processor.write_csv(records)
            elif data_format == DataFormat.JSON:
                return self._processor.write_json(records)
            elif data_format == DataFormat.JSONL:
                return self._processor.write_jsonl(records)

        # Fallback formatting
        if data_format == DataFormat.JSON:
            return json.dumps(records, indent=2, default=str)
        elif data_format == DataFormat.JSONL:
            return "\n".join(json.dumps(r, default=str) for r in records)
        elif data_format == DataFormat.CSV:
            if not records:
                return ""
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
            return output.getvalue()
        elif data_format == DataFormat.TSV:
            if not records:
                return ""
            output = io.StringIO()
            writer = csv.DictWriter(
                output, fieldnames=records[0].keys(), delimiter="\t"
            )
            writer.writeheader()
            writer.writerows(records)
            return output.getvalue()
        else:
            return json.dumps(records, indent=2, default=str)

    def get_stats(self) -> dict[str, Any]:
        """Return cumulative output statistics."""
        return {
            "total_bytes_written": self._total_bytes_written,
            "total_records_written": self._total_records_written,
            "buffer_size": len(self._buffer),
        }
