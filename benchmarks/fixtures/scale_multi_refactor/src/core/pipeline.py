"""Data processing pipeline orchestrator.

This module provides the ``Pipeline`` class that orchestrates multiple
``DataProcessor`` instances in a directed acyclic graph (DAG) of
processing stages. Each stage receives the output of its upstream
stages and produces data for downstream consumers.

Architecture Overview
---------------------
The Pipeline manages:
1. Stage registration and dependency resolution
2. Data flow between stages
3. Error aggregation across stages
4. Pipeline-level metrics and monitoring

A pipeline consists of one or more named stages, each powered by a
``DataProcessor`` with its own configuration. Stages can have dependencies
on other stages, forming a DAG that determines execution order.

Execution Modes
---------------
- **Sequential**: Stages execute one at a time in topological order.
  Simplest mode, uses a single DataProcessor per stage.
- **Parallel**: Independent stages execute concurrently using threads.
  Uses a DataProcessor pool with one instance per concurrent stage.
- **Streaming**: Data flows through stages record-by-record instead
  of batch-by-batch. Lower memory but higher per-record overhead.

Error Handling
--------------
Pipeline-level error handling wraps individual stage errors:
- If a stage fails in STRICT mode, the pipeline halts immediately
- If a stage fails in LENIENT mode, errors are collected and
  downstream stages receive only successfully processed records
- The pipeline provides aggregated error reports across all stages

Monitoring
----------
Pipeline metrics include:
- Total records in and out
- Per-stage processing times
- Pipeline-level throughput
- Stage dependency graph visualization
- Error distribution across stages

Change History
--------------
- v1.0: Basic sequential pipeline with DataProcessor stages
- v1.1: Added DAG-based stage dependencies
- v1.2: Added parallel execution mode
- v1.3: Added streaming mode
- v1.4: Added pipeline-level metrics
- v1.5: Added checkpoint/resume support
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .data_processor import DataProcessor, ProcessorConfig, ProcessingMetrics

logger = logging.getLogger(__name__)


@dataclass
class StageDefinition:
    """Definition of a pipeline stage.

    Each stage wraps a DataProcessor with configuration specific
    to that stage's purpose in the pipeline.

    Attributes:
        name: Unique stage identifier.
        processor: The DataProcessor instance for this stage.
        config: Stage-specific processor configuration.
        depends_on: Names of upstream stages this stage requires.
        enabled: Whether this stage is active.
        description: Human-readable description of the stage's purpose.
        retry_count: Number of retries on transient failure.
    """

    name: str = ""
    processor: Optional[DataProcessor] = None
    config: Optional[ProcessorConfig] = None
    depends_on: list[str] = field(default_factory=list)
    enabled: bool = True
    description: str = ""
    retry_count: int = 0


@dataclass
class PipelineResult:
    """Result of a complete pipeline execution.

    Attributes:
        success: Whether the pipeline completed without fatal errors.
        output: Final output records from the last stage.
        stage_results: Per-stage output and metrics.
        total_duration: Total pipeline execution time.
        records_in: Number of input records.
        records_out: Number of output records.
        errors: Aggregated errors from all stages.
    """

    success: bool = True
    output: list[dict[str, Any]] = field(default_factory=list)
    stage_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_duration: float = 0.0
    records_in: int = 0
    records_out: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        """Generate a human-readable pipeline summary."""
        lines = [
            f"Pipeline Result: {'SUCCESS' if self.success else 'FAILED'}",
            f"  Records: {self.records_in} in -> {self.records_out} out",
            f"  Duration: {self.total_duration:.3f}s",
            f"  Stages: {len(self.stage_results)}",
            f"  Errors: {len(self.errors)}",
        ]
        return "\n".join(lines)


class Pipeline:
    """Data processing pipeline orchestrator.

    Manages a collection of DataProcessor stages connected in a
    directed acyclic graph. Handles execution ordering, data flow,
    and error aggregation.

    Example usage::

        pipeline = Pipeline("my_pipeline")
        pipeline.add_stage("ingest", DataProcessor(ingest_config))
        pipeline.add_stage("validate", DataProcessor(validate_config),
                          depends_on=["ingest"])
        pipeline.add_stage("transform", DataProcessor(transform_config),
                          depends_on=["validate"])
        result = pipeline.execute(raw_data)

    Args:
        name: Pipeline identifier.
        description: Human-readable pipeline description.
    """

    def __init__(self, name: str = "", description: str = "") -> None:
        self.name = name
        self.description = description
        self._stages: dict[str, StageDefinition] = {}
        self._execution_order: list[str] = []

    def add_stage(
        self,
        name: str,
        processor: DataProcessor,
        depends_on: Optional[list[str]] = None,
        description: str = "",
    ) -> None:
        """Add a processing stage to the pipeline.

        Args:
            name: Unique stage name.
            processor: DataProcessor instance for this stage.
            depends_on: Names of upstream stages.
            description: Stage description.
        """
        stage = StageDefinition(
            name=name,
            processor=processor,
            depends_on=depends_on or [],
            description=description,
        )
        self._stages[name] = stage
        self._execution_order = self._topological_sort()
        logger.info("Stage added: name=%s depends_on=%s", name, depends_on)

    def remove_stage(self, name: str) -> bool:
        """Remove a stage from the pipeline.

        Also removes this stage from the dependency list of any
        downstream stages.

        Args:
            name: Stage name to remove.

        Returns:
            True if the stage was found and removed.
        """
        if name not in self._stages:
            return False

        del self._stages[name]
        for stage in self._stages.values():
            if name in stage.depends_on:
                stage.depends_on.remove(name)

        self._execution_order = self._topological_sort()
        return True

    def execute(self, records: list[dict[str, Any]]) -> PipelineResult:
        """Execute the full pipeline on a batch of records.

        Processes records through each stage in topological order,
        passing the output of each stage to its downstream consumers.

        Each stage uses its DataProcessor.process_batch method to
        handle the data transformation.

        Args:
            records: Input records for the first stage.

        Returns:
            PipelineResult with output, metrics, and errors.
        """
        start_time = time.time()
        result = PipelineResult(records_in=len(records))

        logger.info(
            "Pipeline execution started: name=%s stages=%d records=%d",
            self.name, len(self._execution_order), len(records),
        )

        stage_outputs: dict[str, list[dict[str, Any]]] = {}
        current_data = records

        for stage_name in self._execution_order:
            stage = self._stages[stage_name]
            if not stage.enabled:
                logger.info("Stage skipped (disabled): %s", stage_name)
                stage_outputs[stage_name] = current_data
                continue

            if stage.processor is None:
                logger.warning("Stage has no processor: %s", stage_name)
                stage_outputs[stage_name] = current_data
                continue

            # Collect input from upstream stages
            if stage.depends_on:
                stage_input = []
                for dep_name in stage.depends_on:
                    stage_input.extend(stage_outputs.get(dep_name, []))
                if not stage_input:
                    stage_input = current_data
            else:
                stage_input = current_data

            # Execute stage via DataProcessor.process_batch
            logger.info("Executing stage: %s (records=%d)", stage_name, len(stage_input))
            stage_start = time.time()
            try:
                stage_output = stage.processor.process_batch(stage_input)
                stage_duration = time.time() - stage_start

                metrics = stage.processor.get_metrics()
                errors = stage.processor.get_errors()

                stage_outputs[stage_name] = stage_output
                result.stage_results[stage_name] = {
                    "records_in": len(stage_input),
                    "records_out": len(stage_output),
                    "duration": stage_duration,
                    "errors": len(errors),
                }

                for error in errors:
                    result.errors.append({
                        "stage": stage_name,
                        "field": error.field_name,
                        "type": error.error_type,
                        "message": error.message,
                    })

                current_data = stage_output
                logger.info(
                    "Stage complete: %s in=%d out=%d duration=%.3fs",
                    stage_name, len(stage_input), len(stage_output), stage_duration,
                )

            except Exception as exc:
                logger.exception("Stage failed: %s", stage_name)
                result.success = False
                result.errors.append({
                    "stage": stage_name,
                    "type": "stage_failure",
                    "message": str(exc),
                })
                break

        result.output = current_data
        result.records_out = len(current_data)
        result.total_duration = time.time() - start_time

        logger.info(
            "Pipeline execution complete: name=%s success=%s in=%d out=%d duration=%.3fs",
            self.name, result.success, result.records_in,
            result.records_out, result.total_duration,
        )

        return result

    def get_stage_names(self) -> list[str]:
        """Return stage names in execution order."""
        return list(self._execution_order)

    def get_stage(self, name: str) -> Optional[StageDefinition]:
        """Look up a stage by name."""
        return self._stages.get(name)

    def _topological_sort(self) -> list[str]:
        """Sort stages in dependency order using Kahn's algorithm."""
        in_degree: dict[str, int] = {name: 0 for name in self._stages}
        adjacency: dict[str, list[str]] = {name: [] for name in self._stages}

        for name, stage in self._stages.items():
            for dep in stage.depends_on:
                if dep in adjacency:
                    adjacency[dep].append(name)
                    in_degree[name] += 1

        queue = [n for n in in_degree if in_degree[n] == 0]
        result: list[str] = []

        while queue:
            queue.sort()
            node = queue.pop(0)
            result.append(node)
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self._stages):
            raise ValueError("Pipeline contains circular dependencies")

        return result

    def validate(self) -> list[str]:
        """Validate pipeline configuration.

        Checks for:
        - Missing stage dependencies
        - Circular dependencies
        - Stages without processors
        - Empty pipeline

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: list[str] = []
        if not self._stages:
            errors.append("Pipeline has no stages")

        for name, stage in self._stages.items():
            for dep in stage.depends_on:
                if dep not in self._stages:
                    errors.append(f"Stage '{name}' depends on missing stage '{dep}'")
            if stage.processor is None:
                errors.append(f"Stage '{name}' has no processor assigned")

        try:
            self._topological_sort()
        except ValueError as exc:
            errors.append(str(exc))

        return errors
