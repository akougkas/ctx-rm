# Technology Stack

**Analysis Date:** 2026-02-05

## Languages

**Primary:**
- Python 3.12+ (requires >=3.12, venv uses 3.13) - All application code

**Secondary:**
- None

## Runtime

**Environment:**
- Python 3.12.3+ (system)
- Python 3.13 (active venv)

**Package Manager:**
- uv 0.9.2 (modern Python package manager)
- Lockfile: `uv.lock` present (287,227 bytes, committed)

## Frameworks

**Core:**
- Pydantic 2.10+ - Data validation and settings management
- Pydantic Settings 2.7+ - Environment variable configuration
- Typer 0.15+ - CLI framework (built on Click)
- Rich 13.9+ - Terminal formatting and output
- Structlog 24.4+ - Structured logging

**Testing:**
- pytest 8.3+ - Test framework
- pytest-asyncio 0.25+ - Async test support
- pytest-cov 6.0+ - Coverage reporting

**Build/Dev:**
- Hatchling - Build backend (PEP 517)
- Ruff 0.9+ - Linting and formatting (replaces Black, isort, flake8)
- mypy 1.14+ - Static type checking (strict mode enabled)

## Key Dependencies

**Critical:**
- orjson 3.10+ - Fast JSON serialization (used for CLI output parsing and data storage)
- anyio 4.8+ - Async I/O abstraction layer (enables async eviction watcher)
- numpy 2.2+ - Numerical operations (likely for scoring/benchmark analysis)
- structlog 24.4+ - Structured logging throughout the system

**Infrastructure:**
- sqlite3 (stdlib) - Cold storage for evicted segments (`TieredStore` persistence)
- asyncio (stdlib) - Async task management for `Watcher` background loop

**Optional Groups:**
- `gemini`: google-genai 1.0+ (Gemini API client for future LLM-based scoring)
- `claude`: No additional packages (uses npm-installed `@anthropic-ai/claude-code` CLI)
- `bench`: matplotlib 3.10+, pandas 2.2+, tabulate 0.9+ (benchmark visualization and analysis)
- `dev`: Full dev tooling (pytest, ruff, mypy)
- `all`: All optional dependencies combined

## Configuration

**Environment:**
- Configuration via `pydantic-settings` (env vars or `.env` file)
- Prefix: `CTX_RM_*` (e.g., `CTX_RM_TOKEN_BUDGET=200000`)
- Key configs: token budgets, eviction policy, DB path, driver selection
- `.env` file supported but not required (see `src/ctx_rm/config.py`)

**Build:**
- `pyproject.toml` - PEP 621 project metadata
- `tool.ruff` - Linting config (target-version: py312, line-length: 100)
- `tool.pytest.ini_options` - Test discovery and async mode
- `tool.mypy` - Strict type checking (python_version: 3.12)

## Platform Requirements

**Development:**
- Python 3.12+ required (uses `>=3.12` syntax and features)
- uv package manager (recommended, not required - can use pip)
- Optional: `gemini` CLI (npm package `@google/gemini-cli`) for Gemini driver
- Optional: `claude` CLI (npm package `@anthropic-ai/claude-code`) for Claude driver

**Production:**
- Python 3.12+ runtime
- CLI tool installable via `pip install -e .` or `uv sync`
- Entry point: `ctx-rm` command (registered via `project.scripts`)
- No external service dependencies (uses subprocess to invoke agent CLIs)
- Storage: SQLite (embedded, no server)

---

*Stack analysis: 2026-02-05*
