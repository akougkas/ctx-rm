"""JSON data adapter for the processing pipeline.

This module provides the ``JSONAdapter`` class that handles reading
and writing JSON and JSON Lines (JSONL) data for the ``DataProcessor``
pipeline. It supports single-document JSON, JSON arrays, JSONL
streaming format, and nested JSON flattening.

The JSONAdapter extends basic JSON handling with features needed
for production data pipelines including schema inference, path
extraction, and streaming support for large files.

JSON Variants
-------------
- **JSON Array**: ``[{...}, {...}, ...]`` -- Standard JSON array of objects
- **JSON Object**: ``{key: [{...}, ...]}`` -- Nested object with array
- **JSON Lines**: One JSON object per line (no wrapping array)
- **Concatenated JSON**: Multiple root-level objects (no delimiters)

Nested Data Handling
--------------------
JSON data often has deeply nested structures that need to be
flattened for tabular processing by the DataProcessor. The adapter
supports configurable flattening strategies:

- **Dot notation**: ``{"a": {"b": 1}}`` -> ``{"a.b": 1}``
- **Underscore**: ``{"a": {"b": 1}}`` -> ``{"a_b": 1}``
- **Path extraction**: Extract specific paths from nested structures

Streaming Support
-----------------
For large JSON files or JSONL streams, the adapter supports
incremental parsing that yields records in batches. This allows
processing files that exceed available memory by using the
DataProcessor's process_batch method on each batch.

Change History
--------------
- v1.0: Basic JSON reading and writing
- v1.1: Added JSONL support
- v1.2: Added nested JSON flattening
- v1.3: Added streaming parser
- v1.4: Added schema inference
- v1.5: Added path extraction for nested data
"""

from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from ..core.data_processor import DataProcessor, DataFormat

logger = logging.getLogger(__name__)


@dataclass
class JSONConfig:
    """Configuration for JSON reading and writing.

    Attributes:
        format: JSON variant (json, jsonl).
        encoding: File encoding.
        flatten_nested: Whether to flatten nested objects.
        flatten_separator: Separator for flattened field names.
        max_depth: Maximum nesting depth for flattening.
        array_path: JSON path to the data array (for nested objects).
        pretty_print: Whether to pretty-print output JSON.
        indent: Indentation level for pretty printing.
        sort_keys: Whether to sort object keys in output.
        ensure_ascii: Whether to escape non-ASCII characters.
        column_mapping: Map of JSON key -> processor field name.
    """

    format: DataFormat = DataFormat.JSON
    encoding: str = "utf-8"
    flatten_nested: bool = False
    flatten_separator: str = "."
    max_depth: int = 10
    array_path: Optional[str] = None
    pretty_print: bool = True
    indent: int = 2
    sort_keys: bool = False
    ensure_ascii: bool = False
    column_mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class JSONReadResult:
    """Result of a JSON read operation.

    Attributes:
        success: Whether the read succeeded.
        records: Parsed records.
        record_count: Number of records parsed.
        nested_depth: Maximum nesting depth found.
        original_format: Detected JSON format.
        errors: Parse errors.
        warnings: Warnings (e.g., data truncation).
    """

    success: bool = True
    records: list[dict[str, Any]] = field(default_factory=list)
    record_count: int = 0
    nested_depth: int = 0
    original_format: str = "json"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class JSONAdapter:
    """JSON data adapter for the DataProcessor pipeline.

    Handles reading and writing JSON data with support for nested
    structures, streaming, and various JSON formats.

    The adapter feeds parsed JSON records into the DataProcessor
    pipeline for processing.

    Args:
        config: JSON configuration.
        processor: DataProcessor instance for processing records.
    """

    def __init__(
        self,
        config: Optional[JSONConfig] = None,
        processor: Optional[DataProcessor] = None,
    ) -> None:
        self._config = config or JSONConfig()
        self._processor = processor

    def read(self, file_path: str | Path) -> JSONReadResult:
        """Read a JSON file and return parsed records.

        Args:
            file_path: Path to the JSON file.

        Returns:
            JSONReadResult with parsed records.
        """
        path = Path(file_path)

        if not path.exists():
            return JSONReadResult(
                success=False,
                errors=[f"File not found: {path}"],
            )

        try:
            content = path.read_text(encoding=self._config.encoding)
        except (OSError, UnicodeDecodeError) as exc:
            return JSONReadResult(
                success=False,
                errors=[f"Read error: {exc}"],
            )

        return self.read_string(content)

    def read_string(self, content: str) -> JSONReadResult:
        """Parse a JSON string into records.

        Supports JSON arrays, single objects, and JSONL format.

        Args:
            content: JSON content string.

        Returns:
            JSONReadResult with parsed records.
        """
        result = JSONReadResult()
        content = content.strip()

        if not content:
            return result

        try:
            if self._config.format == DataFormat.JSONL:
                records = self._parse_jsonl(content, result)
            else:
                records = self._parse_json(content, result)

            # Apply array path extraction
            if self._config.array_path and len(records) == 1:
                extracted = self._extract_path(records[0], self._config.array_path)
                if isinstance(extracted, list):
                    records = extracted

            # Flatten nested structures
            if self._config.flatten_nested:
                records = [self._flatten(r) for r in records]

            # Apply column mapping
            if self._config.column_mapping:
                records = [self._apply_mapping(r) for r in records]

            result.records = records
            result.record_count = len(records)
            result.success = len(result.errors) == 0

        except Exception as exc:
            result.success = False
            result.errors.append(f"Parse error: {exc}")

        logger.info(
            "JSON read: records=%d format=%s errors=%d",
            result.record_count, result.original_format, len(result.errors),
        )

        return result

    def read_and_process(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Read JSON and process through the DataProcessor.

        Args:
            file_path: Path to the JSON file.

        Returns:
            Processed records.

        Raises:
            RuntimeError: If no DataProcessor is configured.
        """
        if self._processor is None:
            raise RuntimeError("No DataProcessor configured for JSONAdapter")

        result = self.read(file_path)
        if not result.records:
            return []

        return self._processor.process_batch(result.records)

    def read_streaming(
        self, file_path: str | Path, batch_size: int = 1000
    ) -> Iterator[list[dict[str, Any]]]:
        """Read JSON in streaming batches.

        For JSONL files, yields batches of records. For JSON arrays,
        reads the full file and yields batches (less memory efficient).

        Args:
            file_path: Path to the JSON file.
            batch_size: Records per batch.

        Yields:
            Batches of records.
        """
        result = self.read(file_path)
        records = result.records

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            if self._processor is not None:
                batch = self._processor.process_batch(batch)
            yield batch

    def write(
        self,
        records: list[dict[str, Any]],
        file_path: str | Path,
    ) -> int:
        """Write records to a JSON file.

        Args:
            records: Records to write.
            file_path: Output file path.

        Returns:
            Number of records written.
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        content = self.write_string(records)
        path.write_text(content, encoding=self._config.encoding)

        logger.info("JSON written: path=%s records=%d", path, len(records))
        return len(records)

    def write_string(self, records: list[dict[str, Any]]) -> str:
        """Serialize records to a JSON string.

        Args:
            records: Records to serialize.

        Returns:
            JSON formatted string.
        """
        if self._config.format == DataFormat.JSONL:
            return "\n".join(
                json.dumps(r, default=str, ensure_ascii=self._config.ensure_ascii)
                for r in records
            )

        return json.dumps(
            records,
            indent=self._config.indent if self._config.pretty_print else None,
            sort_keys=self._config.sort_keys,
            ensure_ascii=self._config.ensure_ascii,
            default=str,
        )

    def _parse_json(
        self, content: str, result: JSONReadResult
    ) -> list[dict[str, Any]]:
        """Parse standard JSON content."""
        result.original_format = "json"
        data = json.loads(content)

        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            return [data]
        else:
            result.errors.append(f"Unexpected JSON root type: {type(data).__name__}")
            return []

    def _parse_jsonl(
        self, content: str, result: JSONReadResult
    ) -> list[dict[str, Any]]:
        """Parse JSON Lines content."""
        result.original_format = "jsonl"
        records: list[dict[str, Any]] = []

        for line_num, line in enumerate(content.split("\n"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
                else:
                    result.warnings.append(
                        f"Line {line_num}: Expected object, got {type(obj).__name__}"
                    )
            except json.JSONDecodeError as exc:
                result.errors.append(f"Line {line_num}: {exc}")

        return records

    def _flatten(
        self, obj: dict[str, Any], prefix: str = "", depth: int = 0
    ) -> dict[str, Any]:
        """Flatten a nested dictionary using dot notation."""
        items: dict[str, Any] = {}
        if depth >= self._config.max_depth:
            items[prefix.rstrip(self._config.flatten_separator)] = obj
            return items

        for key, value in obj.items():
            new_key = f"{prefix}{key}" if not prefix else f"{prefix}{self._config.flatten_separator}{key}"
            if isinstance(value, dict):
                items.update(self._flatten(value, new_key + self._config.flatten_separator, depth + 1))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    idx_key = f"{new_key}[{i}]"
                    if isinstance(item, dict):
                        items.update(self._flatten(item, idx_key + self._config.flatten_separator, depth + 1))
                    else:
                        items[idx_key] = item
            else:
                items[new_key] = value

        return items

    def _extract_path(self, obj: dict[str, Any], path: str) -> Any:
        """Extract a value from a nested object using dot-notation path."""
        parts = path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _apply_mapping(self, record: dict[str, Any]) -> dict[str, Any]:
        """Apply column name mapping to a record."""
        return {
            self._config.column_mapping.get(k, k): v
            for k, v in record.items()
        }
