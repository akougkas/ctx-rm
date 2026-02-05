# Testing Patterns

**Analysis Date:** 2026-02-05

## Test Framework

**Runner:**
- pytest 8.3+
- Config: `pyproject.toml` (not a separate pytest.ini)

**Assertion Library:**
- Built-in pytest assertions (assert statements)

**Additional plugins:**
- pytest-asyncio 0.25+ (for async test support)
- pytest-cov 6.0+ (for coverage reporting)

**Run Commands:**
```bash
pytest                    # Run all tests
pytest tests/core/        # Run specific directory
pytest -v                 # Verbose output
pytest --cov=src/ctx_rm   # Run with coverage
pytest -k "test_warm"     # Run tests matching pattern
```

**Configuration in `pyproject.toml`:**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

## Test File Organization

**Location:**
- Mirror structure: Tests in `tests/` directory matching `src/ctx_rm/` structure
- Co-location: Not used — separate `tests/` tree

**Naming:**
- Test files: `test_<module>.py` (e.g., `test_graveyard.py`, `test_segment.py`, `test_bus.py`)
- Test functions: `test_<component>_<behavior>` pattern
- Helper functions: `_make_seg()`, `_build_<fixture>()` (leading underscore)

**Structure:**
```
tests/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── test_bus.py
│   ├── test_graveyard.py
│   ├── test_policies.py
│   └── test_segment.py
├── drivers/
│   └── __init__.py
└── watch/
    └── __init__.py
```

## Test Structure

**Suite Organization:**
```python
"""Tests for the Segment data model."""

import time
from ctx_rm.core.segment import Segment, SegmentRole, Tier

# Helper factory functions
def _make_seg(content: str = "test", tokens: int = 100) -> Segment:
    return Segment(content=content, role=SegmentRole.USER, token_count=tokens)

# Test functions grouped by feature
def test_segment_creation():
    seg = Segment(content="hello world", role=SegmentRole.USER, token_count=3)
    assert seg.tier == Tier.ACTIVE
    assert seg.pinned is False

def test_segment_touch():
    seg = Segment(content="test", role=SegmentRole.USER, token_count=1)
    old_access = seg.last_accessed
    time.sleep(0.01)
    seg.touch()
    assert seg.access_count == 1
    assert seg.last_accessed > old_access
```

**Patterns:**
- No test classes (flat function structure)
- Section comments for grouping: `# ── WarmCache ───────...`
- Helper factories at module top
- One assertion concept per test
- Descriptive test names encode behavior

**Setup/Teardown:**
- Minimal use of fixtures (not observed in current tests)
- Fresh object creation per test
- In-memory SQLite (`:memory:`) for database tests
- No conftest.py files in project (only in dependencies)

## Mocking

**Framework:** Not heavily used yet

**Patterns:**
- Prefer in-memory implementations over mocks (SQLite `:memory:`)
- Use real objects with test configuration (smaller boundaries, faster tests)
- Example: `TieredStore(warm_max_items=2)` instead of mocking

**What to Mock:**
- External processes (when needed for CLI drivers)
- Not currently observed in existing tests

**What NOT to Mock:**
- Core data structures (Segment, WarmCache, ColdStore)
- SQLite (use `:memory:` instead)
- Simple state machines

## Fixtures and Factories

**Test Data:**
```python
def _make_seg(content: str = "test", tokens: int = 100, role: str = "user") -> Segment:
    return Segment(content=content, role=SegmentRole(role), token_count=tokens)

def _make_seg(content: str = "test", tokens: int = 100, idle: float = 0) -> Segment:
    seg = Segment(content=content, role=SegmentRole.USER, token_count=tokens)
    if idle > 0:
        seg.last_accessed = time.time() - idle
    return seg
```

**Pattern:**
- Factory functions prefixed with `_` (module-level helpers)
- Default parameters for common cases
- Variation parameters for testing edge cases (`idle`, `tokens`, `role`)
- Multiple factory variants in same module for different test needs

**Location:**
- Factory functions defined at top of test file (after imports)
- No shared fixtures file yet (conftest.py not used)
- Inline object construction for one-off cases

## Coverage

**Requirements:** None enforced (no minimum threshold configured)

**View Coverage:**
```bash
pytest --cov=src/ctx_rm           # Run with coverage
pytest --cov=src/ctx_rm --cov-report=html  # HTML report
pytest --cov=src/ctx_rm --cov-report=term  # Terminal report
```

**Coverage tooling:**
- pytest-cov plugin installed
- No coverage config in pyproject.toml (uses defaults)

## Test Types

**Unit Tests:**
- Scope: Single class or function
- Approach: Test public API, ignore internal state
- Examples:
  - `test_segment_creation()` — tests Segment model
  - `test_warm_cache_put_and_get()` — tests WarmCache in isolation
  - `test_lru_evicts_oldest()` — tests LRU policy logic

**Integration Tests:**
- Scope: Multi-component interactions
- Approach: Real objects with in-memory backends
- Examples:
  - `test_tiered_store_warm_to_cold_cascade()` — tests WarmCache → ColdStore flow
  - `test_ingest_adds_to_active()` — tests ContextBus with TieredStore
  - `test_eviction_triggers_on_budget()` — tests full eviction cycle

**E2E Tests:**
- Framework: Not used yet
- CLI benchmarks serve as E2E validation
- Future: Likely in `benchmarks/` directory with real agent drivers

## Common Patterns

**Async Testing:**
```python
# Pattern: async tests work automatically with asyncio_mode = "auto"
# Not observed in current tests (most are synchronous unit tests)
# When needed:
async def test_driver_invoke():
    driver = GeminiCLIDriver()
    response = await driver.invoke("test prompt")
    assert response.success
```

**Error Testing:**
```python
def test_cold_store_archive():
    store = ColdStore()
    seg = _make_seg("to archive")
    store.persist(seg)
    store.archive(seg.seg_id)

    # Should not appear in normal retrieval
    assert store.retrieve(seg.seg_id) is None
    assert store.archived_count == 1
```

**Pattern:**
- Test "not found" behavior with `None` returns
- Verify side effects (counts, state changes)
- Use real errors, not mocks

**State Verification:**
```python
def test_warm_cache_lru_eviction():
    cache = WarmCache(max_items=2)
    s1 = _make_seg("first", tokens=50)
    s2 = _make_seg("second", tokens=50)
    s3 = _make_seg("third", tokens=50)

    cache.put(s1)
    cache.put(s2)
    aged = cache.put(s3)  # s1 should be aged out

    assert len(aged) == 1
    assert aged[0].seg_id == s1.seg_id
    assert cache.count == 2
```

**Pattern:**
- Setup initial state
- Perform operation
- Assert on both return value and object state
- Multiple assertions per test when verifying related invariants

**Time-based Testing:**
```python
def test_segment_touch():
    seg = Segment(content="test", role=SegmentRole.USER, token_count=1)
    old_access = seg.last_accessed
    time.sleep(0.01)  # Ensure timestamp difference
    seg.touch()
    assert seg.last_accessed > old_access
```

**Pattern:**
- Use `time.sleep()` for timestamp ordering
- Avoid brittle exact timestamp comparisons
- Test ordering (`>`) not exact values

---

*Testing analysis: 2026-02-05*
