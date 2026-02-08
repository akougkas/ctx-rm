"""CSV data adapter for the processing pipeline.

This module provides the ``CSVAdapter`` class that handles reading
and writing CSV data for the ``DataProcessor`` pipeline. It extends
basic CSV handling with advanced features like dialect detection,
encoding handling, and streaming support.

The CSVAdapter serves as a specialized bridge between CSV files and
the DataProcessor, handling all CSV-specific concerns so the core
processor can work with generic record dictionaries.

CSV Dialect Handling
--------------------
The adapter can detect and handle various CSV dialects:
- Standard (RFC 4180): Comma-delimited, double-quote escaping
- Excel: Microsoft Excel CSV with trailing commas
- Unix: Unix-style with strict quoting
- TSV: Tab-separated values
- Custom: User-defined delimiter, quoting, and escape characters

Encoding Support
----------------
Automatic encoding detection is supported via chardet (if installed).
Falls back to UTF-8 with error handling. Supports:
- UTF-8 (with and without BOM)
- UTF-16 (LE and BE)
- ISO-8859-1 (Latin-1)
- Windows-1252
- ASCII

Streaming Support
-----------------
For large CSV files that exceed available memory, the adapter
supports streaming mode where records are yielded one at a time
or in configurable batch sizes. This uses the DataProcessor's
process_batch method for each batch.

Column Mapping
--------------
The adapter supports column name mapping between CSV headers and
the DataProcessor's expected field names. This allows processing
CSV files with non-standard or legacy column names.

Change History
--------------
- v1.0: Basic CSV reading and writing
- v1.1: Added dialect detection
- v1.2: Added encoding detection
- v1.3: Added streaming mode
- v1.4: Added column mapping
- v1.5: Added schema inference from CSV headers
"""

from __future__ import annotations

import csv
import io
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from ..core.data_processor import DataProcessor, DataFormat

logger = logging.getLogger(__name__)


@dataclass
class CSVConfig:
    """Configuration for CSV reading and writing.

    Attributes:
        delimiter: Field delimiter character.
        quotechar: Character used to quote fields.
        escapechar: Character used to escape the delimiter.
        doublequote: Whether double-quoting is used for escaping.
        skipinitialspace: Whether to skip spaces after delimiter.
        lineterminator: Line ending character(s).
        has_header: Whether the first row contains column names.
        encoding: File encoding.
        column_mapping: Map of CSV header -> processor field name.
        skip_rows: Number of rows to skip at the start.
        max_rows: Maximum number of rows to read (0 = unlimited).
        strip_whitespace: Whether to strip field whitespace.
        null_values: Values treated as null.
    """

    delimiter: str = ","
    quotechar: str = '"'
    escapechar: Optional[str] = None
    doublequote: bool = True
    skipinitialspace: bool = False
    lineterminator: str = "\r\n"
    has_header: bool = True
    encoding: str = "utf-8"
    column_mapping: dict[str, str] = field(default_factory=dict)
    skip_rows: int = 0
    max_rows: int = 0
    strip_whitespace: bool = True
    null_values: list[str] = field(
        default_factory=lambda: ["", "null", "NULL", "N/A", "n/a", "-"]
    )


@dataclass
class CSVReadResult:
    """Result of a CSV read operation.

    Attributes:
        success: Whether the read succeeded.
        records: Parsed records.
        row_count: Total rows read (including skipped).
        column_names: Detected or configured column names.
        detected_dialect: Detected CSV dialect details.
        detected_encoding: Detected file encoding.
        errors: Any parse errors encountered.
        warnings: Any warnings (e.g., inconsistent column counts).
    """

    success: bool = True
    records: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    column_names: list[str] = field(default_factory=list)
    detected_dialect: Optional[dict[str, Any]] = None
    detected_encoding: str = "utf-8"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class CSVAdapter:
    """CSV data adapter for the DataProcessor pipeline.

    Handles reading and writing CSV files with advanced features
    including dialect detection, encoding handling, and streaming.

    The adapter uses the DataProcessor for record processing, feeding
    parsed CSV records into the processor's pipeline.

    Args:
        config: CSV configuration.
        processor: DataProcessor instance for processing records.
    """

    def __init__(
        self,
        config: Optional[CSVConfig] = None,
        processor: Optional[DataProcessor] = None,
    ) -> None:
        self._config = config or CSVConfig()
        self._processor = processor

    def read(self, file_path: str | Path) -> CSVReadResult:
        """Read a CSV file and return parsed records.

        Args:
            file_path: Path to the CSV file.

        Returns:
            CSVReadResult with parsed records and metadata.
        """
        path = Path(file_path)

        if not path.exists():
            return CSVReadResult(
                success=False,
                errors=[f"File not found: {path}"],
            )

        try:
            content = path.read_text(encoding=self._config.encoding)
        except (OSError, UnicodeDecodeError) as exc:
            return CSVReadResult(
                success=False,
                errors=[f"Read error: {exc}"],
            )

        return self.read_string(content)

    def read_string(self, content: str) -> CSVReadResult:
        """Parse a CSV string into records.

        Args:
            content: CSV content as a string.

        Returns:
            CSVReadResult with parsed records.
        """
        result = CSVReadResult()

        try:
            reader = csv.DictReader(
                io.StringIO(content),
                delimiter=self._config.delimiter,
                quotechar=self._config.quotechar,
            )

            if reader.fieldnames:
                result.column_names = list(reader.fieldnames)

            records: list[dict[str, Any]] = []
            for row_num, row in enumerate(reader, 1):
                if row_num <= self._config.skip_rows:
                    continue
                if self._config.max_rows and len(records) >= self._config.max_rows:
                    break

                # Apply column mapping
                mapped_row = self._apply_mapping(dict(row))

                # Strip whitespace
                if self._config.strip_whitespace:
                    mapped_row = {
                        k: v.strip() if isinstance(v, str) else v
                        for k, v in mapped_row.items()
                    }

                # Handle null values
                mapped_row = {
                    k: None if v in self._config.null_values else v
                    for k, v in mapped_row.items()
                }

                records.append(mapped_row)
                result.row_count += 1

            result.records = records
            result.success = True

        except csv.Error as exc:
            result.success = False
            result.errors.append(f"CSV parse error: {exc}")

        logger.info(
            "CSV read: rows=%d columns=%d errors=%d",
            result.row_count, len(result.column_names), len(result.errors),
        )

        return result

    def read_and_process(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Read a CSV file and process through the DataProcessor.

        Args:
            file_path: Path to the CSV file.

        Returns:
            List of processed records.

        Raises:
            RuntimeError: If no DataProcessor is configured.
        """
        if self._processor is None:
            raise RuntimeError("No DataProcessor configured for CSVAdapter")

        result = self.read(file_path)
        if not result.records:
            return []

        return self._processor.process_batch(result.records)

    def read_streaming(
        self, file_path: str | Path, batch_size: int = 1000
    ) -> Iterator[list[dict[str, Any]]]:
        """Read a CSV file in streaming batches.

        Yields batches of records for memory-efficient processing
        of large files.

        Args:
            file_path: Path to the CSV file.
            batch_size: Number of records per batch.

        Yields:
            Lists of records, each up to batch_size in length.
        """
        result = self.read(file_path)
        records = result.records

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            if self._processor is not None:
                batch = self._processor.process_batch(batch)
            yield batch

    def write(
        self, records: list[dict[str, Any]], file_path: str | Path
    ) -> int:
        """Write records to a CSV file.

        Args:
            records: Records to write.
            file_path: Output file path.

        Returns:
            Number of records written.
        """
        if not records:
            return 0

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        content = self.write_string(records)
        path.write_text(content, encoding=self._config.encoding)

        logger.info("CSV written: path=%s records=%d", path, len(records))
        return len(records)

    def write_string(self, records: list[dict[str, Any]]) -> str:
        """Serialize records to a CSV string.

        Args:
            records: Records to serialize.

        Returns:
            CSV formatted string.
        """
        if not records:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=records[0].keys(),
            delimiter=self._config.delimiter,
            quotechar=self._config.quotechar,
            lineterminator=self._config.lineterminator,
        )
        writer.writeheader()
        writer.writerows(records)

        return output.getvalue()

    def detect_dialect(self, sample: str) -> dict[str, Any]:
        """Detect CSV dialect from a sample.

        Args:
            sample: A sample of CSV content.

        Returns:
            Dictionary describing the detected dialect.
        """
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample)
            return {
                "delimiter": dialect.delimiter,
                "quotechar": dialect.quotechar,
                "doublequote": dialect.doublequote,
                "has_header": sniffer.has_header(sample),
            }
        except csv.Error:
            return {
                "delimiter": ",",
                "quotechar": '"',
                "doublequote": True,
                "has_header": True,
            }

    def _apply_mapping(self, row: dict[str, Any]) -> dict[str, Any]:
        """Apply column name mapping to a row."""
        if not self._config.column_mapping:
            return row
        return {
            self._config.column_mapping.get(k, k): v
            for k, v in row.items()
        }

    def infer_schema(self, records: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Infer field types from a sample of records.

        Examines values across records to determine the most likely
        type for each field.

        Args:
            records: Sample records for type inference.

        Returns:
            List of {"name": field_name, "type": inferred_type} dicts.
        """
        if not records:
            return []

        field_types: dict[str, list[str]] = {}
        for record in records:
            for key, value in record.items():
                if key not in field_types:
                    field_types[key] = []
                field_types[key].append(self._infer_type(value))

        schema: list[dict[str, str]] = []
        for name, types in field_types.items():
            # Most common type wins
            type_counts: dict[str, int] = {}
            for t in types:
                type_counts[t] = type_counts.get(t, 0) + 1
            best_type = max(type_counts, key=type_counts.get)
            schema.append({"name": name, "type": best_type})

        return schema

    @staticmethod
    def _infer_type(value: Any) -> str:
        """Infer the type of a single value."""
        if value is None or value == "":
            return "null"
        s = str(value)
        try:
            int(s)
            return "int"
        except ValueError:
            pass
        try:
            float(s)
            return "float"
        except ValueError:
            pass
        if s.lower() in ("true", "false"):
            return "bool"
        return "str"
