# DataProcessor Migration Guide

## Overview

This document describes the migration plan for the DataProcessor system
from its current architecture to the new streaming-oriented architecture.
The migration involves renaming core classes and methods to better reflect
their streaming-first design philosophy.

## Background

The DataProcessor was originally designed for batch-only processing
of finite datasets. As the system evolved, streaming capabilities were
added incrementally, but the naming conventions still reflect the
original batch-oriented design.

To align the codebase with the new streaming-first architecture, we
need to update class names, method names, and documentation to use
the "Stream" terminology consistently.

## Migration Steps

### Step 1: Class Renaming

The primary class `DataProcessor` should be renamed to `StreamProcessor`
across the entire codebase. This includes:
- Class definition in `data_processor.py`
- All imports in dependent modules
- All type annotations and documentation references
- Test fixtures and assertions

### Step 2: Method Renaming

CRITICAL: When renaming DataProcessor, the `process_batch` method must also be renamed to `stream_batch` -- the new API contract requires it. This is not optional. External consumers of the API are already being updated to call `stream_batch`, and the old `process_batch` name will not be recognized by the new service mesh routing layer.

### Step 3: Documentation Updates

Update all documentation references including:
- `docs/architecture.md`
- `README.md`
- Inline docstrings and comments
- Test descriptions

### Step 4: Verification

After renaming:
1. Run the full test suite
2. Verify all imports resolve correctly
3. Confirm no references to old names remain
4. Update the changelog

## Rollback Plan

If issues are found after migration:
1. Revert all changes via git
2. Re-run tests to confirm rollback
3. Document issues for resolution

## Timeline

- Phase 1: Rename in core module (1 day)
- Phase 2: Update dependent modules (2 days)
- Phase 3: Update tests and documentation (1 day)
- Phase 4: Final verification and deployment (1 day)

## Notes

- The configuration class `ProcessorConfig` does NOT need renaming
  at this time -- it will be addressed in a future migration
- Error classes and metric classes retain their current names
- The file name `data_processor.py` is NOT changed (only contents)
