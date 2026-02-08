# DataProcessor Pipeline

A configurable data processing pipeline for batch and streaming workloads.

## Overview

The DataProcessor system provides a modular architecture for ingesting,
validating, transforming, and outputting structured data. It supports
multiple input/output formats (CSV, JSON, JSONL) and can be configured
with custom schemas, transforms, and validation rules.

## Quick Start

```python
from core.data_processor import DataProcessor, ProcessorConfig, FieldSchema

# Configure the processor
config = ProcessorConfig(
    schema=[
        FieldSchema(name="name", required=True),
        FieldSchema(name="email", required=True, pattern=r"^[^@]+@[^@]+$"),
        FieldSchema(name="age", field_type="int", min_value=0),
    ],
    strip_whitespace=True,
    dedup_fields=["email"],
)

# Process data
processor = DataProcessor(config)
results = processor.process_batch(records)

# Check metrics
metrics = processor.get_metrics()
print(f"Processed {metrics.processed_records}/{metrics.total_records} records")
print(f"Throughput: {metrics.throughput:.0f} records/sec")
```

## Installation

```bash
pip install -e .
```

## Project Structure

```
src/
  core/
    data_processor.py    # Core DataProcessor class
    pipeline.py          # Multi-stage pipeline orchestrator
  handlers/
    input_handler.py     # Input source handling
    output_handler.py    # Output destination handling
  validators/
    schema_validator.py  # Schema validation
    data_validator.py    # Data quality validation
  adapters/
    csv_adapter.py       # CSV format adapter
    json_adapter.py      # JSON format adapter
tests/
  test_pipeline.py       # Comprehensive test suite
docs/
  architecture.md        # System architecture documentation
```

## Key Features

### DataProcessor

The `DataProcessor` class is the core component:

- **Schema Validation**: Define field types, constraints, and patterns
- **Transforms**: Built-in and custom field transformations
- **Deduplication**: Remove duplicate records by key fields
- **Error Handling**: Strict, lenient, or skip modes
- **Metrics**: Processing statistics and throughput tracking
- **Format I/O**: Read/write CSV, JSON, JSONL

The main processing method is `process_batch()`:

```python
processor = DataProcessor()
output = processor.process_batch(input_records)
```

### Pipeline

Chain multiple DataProcessor stages:

```python
from core.pipeline import Pipeline

pipeline = Pipeline("etl")
pipeline.add_stage("ingest", ingest_processor)
pipeline.add_stage("validate", validate_processor, depends_on=["ingest"])
pipeline.add_stage("transform", transform_processor, depends_on=["validate"])
result = pipeline.execute(records)
```

### Adapters

Format-specific adapters wrap the DataProcessor:

```python
from adapters.csv_adapter import CSVAdapter
from adapters.json_adapter import JSONAdapter

csv_adapter = CSVAdapter(processor=DataProcessor(config))
results = csv_adapter.read_and_process("data.csv")
```

## Configuration

### ProcessorConfig Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| schema | list[FieldSchema] | [] | Field definitions |
| error_mode | ErrorMode | LENIENT | Error handling |
| batch_size | int | 1000 | Batch processing size |
| strip_whitespace | bool | True | Strip field whitespace |
| dedup_fields | list[str] | [] | Dedup key fields |
| null_values | list[str] | ["", "null", ...] | Null value strings |

### FieldSchema Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| name | str | "" | Field name |
| field_type | str | "str" | Expected type |
| required | bool | True | Whether required |
| min_value | float | None | Minimum numeric value |
| max_value | float | None | Maximum numeric value |
| pattern | str | None | Regex pattern |
| choices | list | None | Allowed values |
| transform | str | None | Transform function |

## Error Handling

```python
from core.data_processor import ErrorMode

# Stop on first error
config = ProcessorConfig(error_mode=ErrorMode.STRICT)

# Collect errors and continue
config = ProcessorConfig(error_mode=ErrorMode.LENIENT)

# Skip invalid records silently
config = ProcessorConfig(error_mode=ErrorMode.SKIP)
```

## Metrics

```python
processor = DataProcessor()
processor.process_batch(records)
metrics = processor.get_metrics()

print(metrics.to_dict())
# {
#   "total_records": 1000,
#   "processed_records": 985,
#   "skipped_records": 15,
#   "error_count": 15,
#   "success_rate": "98.5%",
#   "duration_seconds": "0.234",
#   "throughput_rps": "4273.5",
# }
```

## Testing

```bash
pytest tests/ -v
```

## Contributing

See `docs/architecture.md` for detailed system documentation.

## License

MIT License
