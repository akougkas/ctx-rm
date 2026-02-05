# Codebase Structure

**Analysis Date:** 2026-02-05

## Directory Layout

```
ctx-rm-worktree/
├── src/ctx_rm/                    # Main package (installed as ctx_rm)
│   ├── core/                      # Core engine: segments, bus, tiers, policies, scorer
│   ├── watch/                     # Background eviction watcher
│   ├── drivers/                   # CLI agent subprocess wrappers
│   ├── telemetry/                 # Metrics collection for benchmarks
│   ├── benchmarks/                # Benchmark runner (3-mode experiments)
│   ├── cli/                       # Typer CLI (ctx-rm command)
│   ├── harness/                   # (Empty) Future: advanced harness features
│   ├── integrations/              # (Empty) Future: external system integrations
│   └── mcp/                       # (Empty) Future: MCP protocol support
├── tests/                         # pytest tests (30 passing)
│   ├── core/                      # Tests for core engine
│   ├── drivers/                   # Tests for drivers (empty)
│   └── watch/                     # Tests for watcher (empty)
├── benchmarks/                    # Task fixtures (future: YAML task definitions)
│   ├── tasks/                     # Task definitions
│   ├── fixtures/                  # Test data for tasks
│   └── analysis/                  # Jupyter notebooks for results analysis
├── docs/                          # Architecture, theory, competitive analysis
├── .planning/                     # GSD planning artifacts
├── pyproject.toml                 # uv project config
├── uv.lock                        # uv lockfile
├── README.md                      # Project overview
├── LICENSE                        # Apache-2.0
├── NEXT-STEPS.md                  # Development roadmap
└── .venv/                         # Virtual environment (uv managed)
```

## Directory Purposes

**src/ctx_rm/core/:**
- Purpose: Core eviction engine and data structures
- Contains: Segment model, ContextBus coordinator, TieredStore (Warm/Cold/Graveyard/Zombie), Scorer, Policies
- Key files:
  - `segment.py`: Segment and Tier models (atomic context unit with lifecycle)
  - `bus.py`: ContextBus (central coordinator, public API)
  - `graveyard.py`: TieredStore, WarmCache, ColdStore, ZombieQueue (multi-tier memory)
  - `scorer.py`: Scorer protocol and HeuristicScorer
  - `policies/`: base.py (protocol), lru.py, clock.py, budget.py

**src/ctx_rm/watch/:**
- Purpose: Background async eviction loop
- Contains: Watcher (asyncio task), WatcherConfig (trigger modes)
- Key files: `watcher.py`

**src/ctx_rm/drivers/:**
- Purpose: CLI agent subprocess wrappers
- Contains: AgentDriver protocol, GeminiCLIDriver, ClaudeCodeDriver
- Key files:
  - `base.py`: AgentDriver protocol, AgentResponse dataclass
  - `gemini.py`: Gemini CLI driver (calls `gemini -p --output-format json`)
  - `claude.py`: Claude Code driver (calls `claude -p --output-format json`)

**src/ctx_rm/telemetry/:**
- Purpose: Research metrics collection
- Contains: MetricsCollector, event dataclasses (IngestEvent, EvictionEvent, RecallEvent, TurnSnapshot)
- Key files: `metrics.py`

**src/ctx_rm/benchmarks/:**
- Purpose: Benchmark orchestrator (3-mode experiments)
- Contains: BenchmarkRunner, task loading (YAML stubs), turn-by-turn invocation, metrics export
- Key files: `runner.py`

**src/ctx_rm/cli/:**
- Purpose: Typer CLI (ctx-rm command)
- Contains: Commands: info, bench, compare
- Key files: `main.py`

**src/ctx_rm/harness/:**
- Purpose: (Empty) Future: advanced harness features for complex task orchestration
- Contains: Placeholder for future development
- Key files: None yet

**src/ctx_rm/integrations/:**
- Purpose: (Empty) Future: external system integrations (e.g., vector databases, embedding APIs)
- Contains: Placeholder for future development
- Key files: None yet

**src/ctx_rm/mcp/:**
- Purpose: (Empty) Future: Model Context Protocol support
- Contains: Placeholder for future development
- Key files: None yet

**tests/core/:**
- Purpose: Unit tests for core engine
- Contains: test_segment.py, test_bus.py, test_graveyard.py, test_policies.py
- Key files: All test_*.py files

**tests/drivers/:**
- Purpose: (Empty) Future: tests for CLI agent drivers
- Contains: __init__.py only

**tests/watch/:**
- Purpose: (Empty) Future: tests for background watcher
- Contains: __init__.py only

**benchmarks/:**
- Purpose: Task definitions and analysis notebooks
- Contains: tasks/ (YAML task definitions), fixtures/ (test data), analysis/ (Jupyter notebooks)
- Key files: None yet (TODO: implement task loading from YAML)

**docs/:**
- Purpose: Architecture, theory, competitive analysis, bibliography
- Contains: Markdown documentation
- Key files: (Not yet read, but README mentions: architecture.md, tiered_graveyard.md, competitive_analysis.md, landscape.md, context_removal_benchmark_tasks.yaml)

**.planning/:**
- Purpose: GSD planning artifacts (codebase maps, phase plans)
- Contains: codebase/ (this document and others)
- Key files: Generated by /gsd:map-codebase

## Key File Locations

**Entry Points:**
- `src/ctx_rm/cli/main.py`: CLI entry point (typer app, `ctx-rm` command)
- `src/ctx_rm/__init__.py`: Package version (__version__ = "0.1.0")

**Configuration:**
- `pyproject.toml`: uv project, dependencies, scripts, build config, ruff/pytest/mypy settings
- `uv.lock`: uv lockfile (287K lines)
- `src/ctx_rm/config.py`: Pydantic settings (not yet read, likely app config)

**Core Logic:**
- `src/ctx_rm/core/bus.py`: ContextBus (ingest, evict, recall, render_context)
- `src/ctx_rm/core/graveyard.py`: TieredStore (demote_to_warm, recall, search)
- `src/ctx_rm/core/segment.py`: Segment model (touch, evict, recall lifecycle methods)
- `src/ctx_rm/core/scorer.py`: HeuristicScorer (score_batch)
- `src/ctx_rm/core/policies/budget.py`: BudgetAwarePolicy (composite score ranking)

**Testing:**
- `tests/core/test_segment.py`: Segment model tests
- `tests/core/test_bus.py`: ContextBus tests
- `tests/core/test_graveyard.py`: TieredStore tests
- `tests/core/test_policies.py`: Policy tests

## Naming Conventions

**Files:**
- snake_case for all Python files: `segment.py`, `graveyard.py`, `runner.py`
- test_*.py for test files: `test_segment.py`, `test_bus.py`
- __init__.py for package initialization (minimal exports)

**Directories:**
- snake_case: `core/`, `watch/`, `drivers/`, `benchmarks/`
- Flat structure within each package (no deep nesting)

**Classes:**
- PascalCase: `Segment`, `ContextBus`, `TieredStore`, `WarmCache`, `ClockPolicy`, `BenchmarkRunner`
- Protocol suffix for ABCs: `EvictionPolicy`, `AgentDriver`, `Scorer`

**Functions/Methods:**
- snake_case: `ingest()`, `run_eviction_cycle()`, `demote_to_warm()`, `score_batch()`
- Public methods: no leading underscore
- Internal helpers: single leading underscore (`_evict_segment()`, `_demote_to_cold()`)

**Variables:**
- snake_case: `token_budget`, `active_tokens`, `headroom_ratio`
- Private instance vars: single leading underscore (`_active`, `_active_tokens`, `_turn`)

**Enums:**
- PascalCase class, UPPER_CASE values: `SegmentRole.USER`, `Tier.ACTIVE`, `TriggerMode.THRESHOLD`

## Where to Add New Code

**New Eviction Policy:**
- Primary code: `src/ctx_rm/core/policies/your_policy.py`
- Tests: `tests/core/test_policies.py` (add new test class)
- Export: Add to `src/ctx_rm/core/policies/__init__.py`
- Integration: Update `BenchmarkRunner._create_policy()` in `src/ctx_rm/benchmarks/runner.py`

**New Scorer:**
- Implementation: `src/ctx_rm/core/scorer.py` (add new class inheriting from Scorer)
- Tests: New file `tests/core/test_scorer.py`
- Integration: Update `BenchmarkRunner._run_ctx_rm_mode()` to allow scorer selection

**New Driver:**
- Primary code: `src/ctx_rm/drivers/your_driver.py`
- Tests: `tests/drivers/test_your_driver.py`
- Export: Add to `src/ctx_rm/drivers/__init__.py`
- Integration: Update `BenchmarkRunner._create_driver()` in `src/ctx_rm/benchmarks/runner.py`

**New CLI Command:**
- Implementation: Add @app.command() decorated function to `src/ctx_rm/cli/main.py`
- No separate file needed (typer single-file pattern)

**New Benchmark Task:**
- Task definition: `benchmarks/tasks/your_task.yaml` (YAML format, see docs/context_removal_benchmark_tasks.yaml)
- Fixtures: `benchmarks/fixtures/your_task/` (codebase snapshots, test data)
- Task loading: Update `BenchmarkRunner._load_task_turns()` to parse YAML

**New Metrics Event:**
- Event dataclass: Add to `src/ctx_rm/telemetry/metrics.py`
- Recording method: Add `record_your_event()` to `MetricsCollector`
- Export: Update `export_json()` to include new event list

**Utilities:**
- Shared helpers: Add to existing module (`src/ctx_rm/core/scorer.py` for scoring utils, `src/ctx_rm/benchmarks/runner.py` for benchmark utils)
- No separate utils/ directory yet (flat structure preferred)

## Special Directories

**.venv/:**
- Purpose: Virtual environment (uv managed)
- Generated: Yes (by `uv sync`)
- Committed: No (in .gitignore)

**.pytest_cache/:**
- Purpose: pytest cache
- Generated: Yes (by pytest)
- Committed: No

**.ruff_cache/:**
- Purpose: ruff linter cache
- Generated: Yes (by ruff)
- Committed: No

**__pycache__/:**
- Purpose: Python bytecode cache
- Generated: Yes (by Python)
- Committed: No (in .gitignore)

**.planning/:**
- Purpose: GSD planning artifacts
- Generated: Yes (by /gsd:map-codebase and other GSD commands)
- Committed: Yes (planning docs are part of the project)

**benchmarks/tasks/, benchmarks/fixtures/, benchmarks/analysis/:**
- Purpose: Task definitions, test data, Jupyter notebooks
- Generated: Partially (tasks/fixtures are authored, analysis notebooks generated)
- Committed: Yes (tasks and fixtures), No (analysis output)

---

*Structure analysis: 2026-02-05*
