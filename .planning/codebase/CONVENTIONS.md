# Coding Conventions

**Analysis Date:** 2026-02-05

## Naming Patterns

**Files:**
- Python modules: lowercase with underscores (`graveyard.py`, `segment.py`, `bus.py`)
- Test files: `test_<module>.py` pattern (`test_graveyard.py`, `test_segment.py`)
- Package markers: `__init__.py` for all packages
- Private implementation: No leading underscore convention for private modules

**Functions:**
- Public methods: snake_case (`ingest()`, `run_eviction_cycle()`, `demote_to_warm()`)
- Private/internal methods: leading underscore (`_make_seg()`, `_fill_to_budget()`, `_evict_segment()`)
- Properties: snake_case with `@property` decorator (`active_tokens`, `budget_remaining`)
- Test functions: `test_<feature>_<behavior>` (`test_warm_cache_put_and_get()`, `test_lru_evicts_oldest()`)

**Variables:**
- Local variables: snake_case (`tokens_to_free`, `aged_out`, `old_tier`)
- Constants: UPPER_SNAKE_CASE (not observed in codebase yet, likely not prevalent)
- Private attributes: leading underscore (`_active`, `_store`, `_turn`)
- Protected attributes: Single underscore prefix (`_db_path`, `_conn`, `_total_tokens`)

**Types:**
- Classes: PascalCase (`Segment`, `TieredStore`, `ContextBus`, `WarmCache`)
- Enums: PascalCase class, UPPER_CASE values (`SegmentRole.USER`, `Tier.ACTIVE`)
- Protocols/ABCs: PascalCase with descriptive suffix (`EvictionPolicy`, `Scorer`, `AgentDriver`)

## Code Style

**Formatting:**
- Tool used: Ruff (version 0.9+)
- Line length: 100 characters (configured in `pyproject.toml`)
- Target version: Python 3.12+

**Key settings:**
```toml
[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src"]
```

**Linting:**
- Tool used: Ruff (combined formatter + linter)
- Rules enabled: E (pycodestyle errors), F (pyflakes), I (isort), N (pep8-naming), W (pycodestyle warnings), UP (pyupgrade), B (flake8-bugbear), SIM (simplify), RUF (Ruff-specific)
- Type checking: mypy with strict mode enabled
- Mypy config: `strict = true`, `warn_return_any = true`, `python_version = "3.12"`

**Import Organization:**

**Order:**
1. Future imports (`from __future__ import annotations`)
2. Standard library imports
3. Third-party imports (grouped together)
4. Local/relative imports

**Pattern observed:**
```python
from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
```

**Conditional imports for type checking:**
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ctx_rm.core.graveyard import TieredStore
    from ctx_rm.core.policies.base import EvictionPolicy
```

**Path Aliases:**
- Absolute imports used throughout (`from ctx_rm.core.segment import Segment`)
- No path aliases configured
- Package structure: `src/ctx_rm/` layout with explicit package in pyproject.toml

## Error Handling

**Patterns:**
- Minimal explicit exception handling observed
- Return `None` for not-found cases (`get()`, `retrieve()`, `recall()`)
- Return empty lists for empty results (`search()`, `select_evictions()`)
- Let exceptions propagate for unexpected errors
- Timeouts handled with `asyncio.wait_for()` and caught as `TimeoutError`
- File operations use try-except for `FileNotFoundError` with fallback

**Example from `src/ctx_rm/drivers/gemini.py`:**
```python
except TimeoutError:
    return AgentResponse(text="", success=False, error=f"Timeout after {timeout}s")
except FileNotFoundError:
    return AgentResponse(text="", success=False, error="gemini CLI not found...")
```

**Example from `src/ctx_rm/core/graveyard.py`:**
```python
def retrieve(self, seg_id: str) -> Segment | None:
    row = self._conn.execute(...).fetchone()
    if row is None:
        return None
    return self._row_to_segment(row)
```

## Logging

**Framework:** structlog (version 24.4+)

**Patterns:**
- Use `structlog.get_logger()` at module level: `logger = structlog.get_logger()`
- Structured logging with key-value pairs: `logger.debug("event_name", key=value, ...)`
- Event-based naming: descriptive event names as first argument (`"segment_ingested"`, `"recall_from_warm"`, `"eviction_cycle_complete"`)
- Log levels observed:
  - `logger.debug()`: Detailed tracing (segment operations, recalls)
  - `logger.info()`: Important state changes (eviction cycles, recalls)
  - `logger.warning()`: Recoverable issues (recall misses)
  - `logger.error()`: Failures (timeouts, subprocess errors)

**Example from `src/ctx_rm/core/bus.py`:**
```python
logger.debug(
    "segment_ingested",
    seg_id=segment.seg_id,
    tokens=segment.token_count,
    active_total=self._active_tokens,
    budget=self.token_budget,
)
```

## Comments

**When to Comment:**
- Module docstrings: Every module has a docstring explaining purpose and architecture
- Class docstrings: Every class documents its role and design inspiration
- Method docstrings: Public methods have concise docstrings
- Inline comments: Used sparingly for non-obvious logic
- Architecture context: Heavy use of comments explaining OS/DB analogies

**JSDoc/TSDoc:**
- Not applicable (Python codebase)
- Google-style docstrings used consistently

**Examples from `src/ctx_rm/core/segment.py`:**
```python
"""Segment: the atomic unit of context in ctx-rm.

A Segment represents a single piece of content in the context window — a user
message, assistant response, tool output, file read, or any other content block.
Segments flow through tiers: Active → Warm → Cold → Graveyard, and can be
recalled as Zombies (page-fault semantics from OS virtual memory).
"""

def touch(self) -> None:
    """Record an access — updates recency, frequency, and ref bit."""
```

**TODOs tracked inline:**
- Format: `# TODO: <description>` in comments
- Examples found:
  - `src/ctx_rm/core/graveyard.py:181`: "TODO: Replace with embedding-based vector search"
  - `src/ctx_rm/core/scorer.py:71`: "TODO: implement content dedup"
  - `src/ctx_rm/benchmarks/runner.py:251`: "TODO: Implement full YAML task loading"

## Function Design

**Size:**
- Methods range from 5-50 lines
- Longer methods broken into sections with blank lines and comments
- Private helper methods extracted for clarity (`_fill_to_budget()`, `_row_to_segment()`)

**Parameters:**
- Use type hints for all parameters and return values
- Optional parameters use `| None` union syntax (modern Python 3.10+ style)
- Default values for optional args: `max_items: int = 64`, `working_dir: str | None = None`
- Use Pydantic `Field()` for model defaults

**Return Values:**
- Explicit return type hints always used
- Return `None` for not-found cases (not exceptions)
- Return empty collections rather than `None` for list results
- Use `| None` union for nullable returns

**Example from `src/ctx_rm/core/bus.py`:**
```python
def run_eviction_cycle(self) -> list[Segment]:
    """Score and evict segments until active context is within budget.

    Returns the list of evicted segments for audit/telemetry.
    """
```

## Module Design

**Exports:**
- Explicit `__all__` in `__init__.py` files
- Example from `src/ctx_rm/core/__init__.py`:
```python
__all__ = ["ContextBus", "Segment", "SegmentRole", "Tier", "TieredStore"]
```

**Barrel Files:**
- Used for major subsystems (core, policies, drivers)
- Re-export key classes from `__init__.py`
- Example from `src/ctx_rm/core/policies/__init__.py`:
```python
from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.policies.budget import BudgetAwarePolicy
from ctx_rm.core.policies.clock import ClockPolicy
from ctx_rm.core.policies.lru import LRUPolicy

__all__ = ["BudgetAwarePolicy", "ClockPolicy", "EvictionPolicy", "LRUPolicy"]
```

**Version management:**
- Single source of truth: `src/ctx_rm/__init__.py` with `__version__ = "0.1.0"`
- Version also in `pyproject.toml` project section

**Separation of concerns:**
- Abstract base classes in `base.py` files
- Implementations in separate files by strategy (lru.py, clock.py, budget.py)
- Clear layering: core → drivers, core → benchmarks

---

*Convention analysis: 2026-02-05*
