# Data Processing Architecture

## System Overview

The data processing system is built around the `DataProcessor` class, which
provides a configurable pipeline for ingesting, validating, transforming,
and outputting structured data records. The system is designed for
high-throughput batch processing with support for streaming extensions.

## Architecture Diagram

```
                    ┌─────────────────┐
                    │   Input Sources  │
                    │  (CSV/JSON/API)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  InputHandler   │
                    │  Format detect  │
                    │  Parse + batch  │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │      DataProcessor          │
              │  ┌─────────────────────┐    │
              │  │  Pre-processing     │    │
              │  │  (strip, normalize) │    │
              │  └─────────┬───────────┘    │
              │  ┌─────────▼───────────┐    │
              │  │  Validation         │    │
              │  │  (schema, types)    │    │
              │  └─────────┬───────────┘    │
              │  ┌─────────▼───────────┐    │
              │  │  Transformation     │    │
              │  │  (field transforms) │    │
              │  └─────────┬───────────┘    │
              │  ┌─────────▼───────────┐    │
              │  │  Enrichment         │    │
              │  │  (external joins)   │    │
              │  └─────────┬───────────┘    │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │  OutputHandler   │
                    │  Format + write  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Destinations    │
                    │  (File/DB/API)   │
                    └─────────────────┘
```

## Core Components

### DataProcessor (`src/core/data_processor.py`)

The central processing engine. Key features:
- Configurable schema validation
- Field-level transformations
- Deduplication support
- Multiple error handling modes
- Processing metrics collection

The main entry point is the `process_batch()` method, which accepts
a list of record dictionaries and returns processed records.

### Pipeline (`src/core/pipeline.py`)

Orchestrates multiple DataProcessor instances in a DAG. Features:
- Topological stage ordering
- Data flow between stages
- Error aggregation
- Pipeline-level metrics

Each pipeline stage wraps a DataProcessor and can depend on
the output of upstream stages.

### InputHandler (`src/handlers/input_handler.py`)

Bridges external data sources with the DataProcessor:
- Auto-detects file formats (CSV, JSON, JSONL, TSV)
- Handles encoding detection
- Supports batched reading for large files
- Integrates with DataProcessor for read-and-process workflows

### OutputHandler (`src/handlers/output_handler.py`)

Writes processed data to output destinations:
- Multiple output formats (CSV, JSON, JSONL, TSV)
- Output buffering for efficiency
- Uses DataProcessor serialization methods

### SchemaValidator (`src/validators/schema_validator.py`)

Pre-processing schema validation:
- Field presence and type checking
- Pattern matching
- Cross-field constraints
- Works with DataProcessor's FieldSchema definitions

### DataValidator (`src/validators/data_validator.py`)

Post-processing data quality validation:
- Completeness scoring
- Range and pattern checks
- Quality score per record
- Integrates with DataProcessor pipeline

### Adapters

Format-specific adapters that wrap the DataProcessor:

**CSVAdapter** (`src/adapters/csv_adapter.py`):
- Dialect detection
- Column mapping
- Streaming CSV processing via DataProcessor

**JSONAdapter** (`src/adapters/json_adapter.py`):
- JSON and JSONL support
- Nested structure flattening
- Path extraction via DataProcessor

## Data Flow

### Simple Processing

```python
processor = DataProcessor(config)
results = processor.process_batch(records)
```

### Pipeline Processing

```python
pipeline = Pipeline("etl")
pipeline.add_stage("validate", DataProcessor(validate_config))
pipeline.add_stage("transform", DataProcessor(transform_config),
                   depends_on=["validate"])
result = pipeline.execute(records)
```

### File Processing

```python
handler = InputHandler(processor=DataProcessor(config))
results = handler.read_and_process("data.csv")
```

## Error Handling

### Error Modes

| Mode | Behavior |
|------|----------|
| STRICT | Stop on first error |
| LENIENT | Collect errors, continue processing |
| SKIP | Silently skip invalid records |

### Error Types

| Type | Description |
|------|-------------|
| required | Missing required field |
| type | Invalid field type |
| range | Value outside allowed range |
| pattern | Value doesn't match regex |
| choices | Value not in allowed set |
| length | String too short or too long |

## Configuration

### ProcessorConfig

```python
config = ProcessorConfig(
    schema=[
        FieldSchema(name="email", required=True, pattern=r"^[^@]+@[^@]+$"),
        FieldSchema(name="age", field_type="int", min_value=0, max_value=150),
    ],
    error_mode=ErrorMode.LENIENT,
    batch_size=1000,
    strip_whitespace=True,
    dedup_fields=["email"],
)
```

## Performance

### Benchmarks

| Scenario | Records | Duration | Throughput |
|----------|---------|----------|------------|
| Simple pass-through | 10,000 | 0.1s | 100K/s |
| Schema validation | 10,000 | 0.3s | 33K/s |
| Full pipeline (3 stages) | 10,000 | 1.2s | 8.3K/s |
| With dedup + transforms | 10,000 | 0.5s | 20K/s |

### Optimization Tips

1. Minimize schema fields to only what's needed
2. Use SKIP error mode for highest throughput
3. Disable enrichment if not needed
4. Pre-sort data if dedup is configured
5. Use batched reading for files > 100MB

## Security

### Input Sanitization

The DataProcessor performs input sanitization through:
- Whitespace stripping (prevents padding attacks)
- Null value normalization (prevents null injection)
- Pattern validation (prevents format-based attacks)
- Length limits (prevents buffer-overflow-like issues)

### Output Encoding

All output is properly encoded to prevent injection:
- JSON output uses json.dumps with default serializer
- CSV output uses Python's csv module with proper escaping
- No raw string interpolation in output

## Monitoring

### Metrics

The DataProcessor collects these metrics per batch:
- `total_records`: Input record count
- `processed_records`: Successfully processed count
- `skipped_records`: Records that failed validation
- `error_count`: Total validation errors
- `throughput`: Records per second
- `stage_durations`: Time per processing stage

### Logging

All components use Python's standard logging:
- INFO: Processing start/complete, stage transitions
- WARNING: Non-fatal validation issues, missing optional data
- ERROR: Processing failures, file I/O errors
- DEBUG: Individual record processing details

## Future Plans

1. **Streaming Mode**: Process records one at a time instead of batches
2. **Parallel Processing**: Multi-threaded stage execution
3. **Checkpoint/Resume**: Save processing state for recovery
4. **Schema Registry**: Centralized schema management
5. **Data Lineage**: Track record provenance through pipeline

## Appendix

### Dependency Graph

```
data_processor.py (core, no dependencies)
    ├── pipeline.py (depends on data_processor)
    ├── input_handler.py (depends on data_processor)
    ├── output_handler.py (depends on data_processor)
    ├── schema_validator.py (depends on data_processor)
    ├── data_validator.py (depends on data_processor)
    ├── csv_adapter.py (depends on data_processor)
    └── json_adapter.py (depends on data_processor)
```

### Glossary

| Term | Definition |
|------|------------|
| Batch | A group of records processed together |
| Stage | A processing step in a pipeline |
| Schema | Definition of expected data structure |
| Transform | A function that modifies field values |
| Enrichment | Adding data from external sources |
| Dedup | Removing duplicate records |
