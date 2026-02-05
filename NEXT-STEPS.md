# NEXT-STEPS: ctx-rm Development Roadmap

> **This document is the handoff prompt for the next Claude Code session(s).**
> It contains everything needed to continue building ctx-rm using the
> [GSD (Get Shit Done)](https://github.com/glittercowboy/get-shit-done) framework.

---

## Before You Begin

**Install and initialize GSD:**

```bash
npx get-shit-done-cc
```

Then run `/gsd:map-codebase` first — ctx-rm already has a working codebase with
24 Python source files, 30 passing tests, full docs, and a CLI. The codebase
mapper will understand the architecture before planning begins.

After mapping, run `/gsd:new-project` or `/gsd:new-milestone` (since this is an
existing project with a working v0.1.0). Feed it this document as context.

---

## What Exists (v0.1.0 — Foundation)

### Core Engine (`src/ctx_rm/core/`)
- **`segment.py`** — Pydantic `Segment` model with 5-tier state (Active/Warm/Cold/Graveyard/Zombie), access tracking (recency, frequency, ref bit), eviction audit trail
- **`bus.py`** — `ContextBus` central coordinator: ingest, score, evict, recall, render context, token budget enforcement with configurable headroom
- **`graveyard.py`** — Full tiered store: `WarmCache` (in-memory LRU), `ColdStore` (SQLite with keyword search + audit log), `ZombieQueue` (page-fault staging), `TieredStore` (orchestrator for all tier transitions)
- **`scorer.py`** — `HeuristicScorer` (exponential recency decay, log-scaled frequency, role weighting). Pluggable `Scorer` ABC.
- **`policies/`** — Three eviction policies: `LRUPolicy`, `ClockPolicy` (PostgreSQL clock-sweep), `BudgetAwarePolicy` (composite score + LRU fallback)

### Background Watcher (`src/ctx_rm/watch/`)
- **`watcher.py`** — Async background eviction loop with 4 trigger modes (interval, threshold, per-turn, hybrid)

### CLI Drivers (`src/ctx_rm/drivers/`)
- **`gemini.py`** — Drives `gemini -p --output-format json --yolo` via subprocess
- **`claude.py`** — Drives `claude -p --output-format json --dangerously-skip-permissions` via subprocess
- Both parse JSON responses for text, token usage, tool calls, timing

### Telemetry (`src/ctx_rm/telemetry/`)
- **`metrics.py`** — Records ingestion/eviction/recall events + per-turn snapshots. Exports to JSON.

### Benchmark Runner (`src/ctx_rm/benchmarks/`)
- **`runner.py`** — Orchestrates 3 modes: Minimal (no history), ctx-rm (ContextBus + Watcher), Full (accumulate all). Drives agents per-turn.

### CLI (`src/ctx_rm/cli/`)
- `ctx-rm info` — Shows drivers + components
- `ctx-rm bench` — Run a benchmark session
- `ctx-rm compare` — Compare results across modes

### Docs (`docs/`)
- `architecture.md` — System design with CLI-first driver architecture
- `tiered_graveyard.md` — OS/DB theoretical foundation (LRU/LFU/CLOCK/ARC/2Q → LLM context)
- `competitive_analysis.md` — Deep analysis of MemAct, SWE-Pruner, ACON
- `landscape.md` — Research bibliography (LLMLingua, MemGPT, Mem0, Zep, LongBench)
- `context_removal_benchmark_tasks.yaml` — 10 structured benchmark tasks with needle injection

### Tests
- 30 tests covering: Segment model, ContextBus, all 3 policies, WarmCache, ColdStore, ZombieQueue, TieredStore (full tier cascade + recall)

### Tech Stack
- Python 3.12+, Astral `uv`, Pydantic v2, Typer, Rich, structlog, orjson, anyio, SQLite

---

## What Needs to Be Built (Milestone 1: "Working Benchmarks")

The following phases should be planned and executed using GSD's
`discuss → plan → execute → verify` cycle. Each phase is designed to be
independently executable with fresh context.

### Phase 1: Task YAML Loader & Fixture Generator

**Goal:** Parse `docs/context_removal_benchmark_tasks.yaml` into executable
multi-turn scenarios and generate the 10 mini-codebase fixtures.

**What to build:**
- `src/ctx_rm/benchmarks/task_loader.py` — YAML parser that reads task definitions (needles, context injections, success criteria, evaluation checks)
- `src/ctx_rm/benchmarks/task_runner.py` — Turn-by-turn executor that injects needles at specified turns, adds noise at specified turns, and evaluates success criteria
- `benchmarks/fixtures/` — 10 mini-repo fixtures (CR-001 through CR-010), each with the minimal codebase needed for the task (e.g., `fixtures/legacy_flag_cascade/` with `src/auth/legacy.py`, `config/flags.py`, etc.)
- `src/ctx_rm/benchmarks/evaluator.py` — Evaluation engine that checks `file_contains`, `file_not_contains`, `file_contains_in_order`, `file_equals` assertions from the YAML

**Key decisions:**
- Each fixture is a self-contained directory with its own files, ready to be copied to a temp dir for each benchmark run
- Needle injection happens by prepending content to the agent's prompt at the specified turn
- Context injections (noise) are synthetic blocks of specified token sizes
- Evaluation runs after all turns complete by inspecting the fixture files

**Tests needed:**
- YAML loading and validation
- Needle injection at correct turns
- Evaluation assertions (all 4 check types)
- Fixture directory structure validation

---

### Phase 2: Embedding-Based Search for ColdStore

**Goal:** Replace the keyword-based `LIKE` search in `ColdStore` with vector
similarity search, enabling semantic recall of evicted segments.

**What to build:**
- Add `numpy`-based cosine similarity search (already a dependency)
- `src/ctx_rm/core/embeddings.py` — Embedding provider interface + lightweight implementation using sentence hashing (for zero-dependency baseline) and optional integration with `sentence-transformers` or Gemini's embedding API
- Update `ColdStore.persist()` to compute and store embeddings
- Update `ColdStore.search()` to use cosine similarity when embeddings are available, fallback to keyword search
- Update `TieredStore.search()` to pass query embeddings

**Key decisions:**
- Default: use a simple hashing-based approach (fast, no ML dependencies)
- Optional: `sentence-transformers` for local embeddings or Gemini `text-embedding-004` via API
- Store embeddings as BLOB in SQLite (numpy array serialized with `numpy.tobytes()`)
- Search returns top-k by cosine similarity with a minimum threshold

**Tests needed:**
- Embedding computation and storage
- Cosine similarity search returns relevant results
- Fallback to keyword search when no embeddings
- Round-trip: persist → search → retrieve

---

### Phase 3: LLM-Based Scorer (Gemini Flash Lite)

**Goal:** Add an LLM-based scorer that uses a fast, cheap model to evaluate
segment relevance to the current task.

**What to build:**
- `src/ctx_rm/core/scorer_llm.py` — `LLMScorer` that calls Gemini Flash Lite (via the Gemini Python SDK `google-genai`) to score segment relevance
- The scorer receives: the current task/goal, the segment content, and minimal context
- Returns a relevance score in [0, 1]
- Batch scoring with rate limiting
- Caching of scores to avoid redundant API calls

**Key decisions:**
- This is the ONE place where we use the Gemini SDK (not CLI) — scoring is a cheap, fast API call, not an agent task. Gemini Flash Lite is essentially free.
- Scoring prompt should be minimal: "Rate the relevance of this content to the task on a scale of 0-1" with structured output
- Cache scores keyed by (segment_hash, task_hash) to avoid re-scoring
- Make this optional — `HeuristicScorer` remains the default, `LLMScorer` is opt-in via config

**Tests needed:**
- Mock the Gemini API call
- Score caching works
- Batch scoring respects rate limits
- Fallback to heuristic on API failure

---

### Phase 4: End-to-End Benchmark Pipeline

**Goal:** Wire everything together so `ctx-rm bench` runs a complete benchmark
with real agents, real tasks, and produces analyzable results.

**What to build:**
- Update `BenchmarkRunner` to use `TaskLoader` for loading YAML tasks
- Update `BenchmarkRunner` to use `TaskRunner` for turn-by-turn execution with needle injection
- Update `BenchmarkRunner` to use `Evaluator` for post-run assessment
- Add `ctx-rm bench --task CR-001 --mode ctx-rm --driver gemini` full pipeline
- Add `ctx-rm bench --all` to run all 10 tasks × 3 modes × 2 drivers
- Results include: metrics JSON + evaluation pass/fail + agent response logs
- `benchmarks/analysis/compare.py` — Script to generate comparison tables from results

**Key decisions:**
- Each benchmark run creates a temp copy of the fixture directory
- Agent runs in the temp dir so file modifications are isolated
- After all turns, evaluator checks the files in the temp dir
- Results go to `results/{task_id}/{mode}/{driver}/` with metrics.json + evaluation.json
- The `compare` command reads all results and generates a summary table

**Tests needed:**
- Full pipeline integration test with a mock driver
- Results directory structure is correct
- Evaluation results are recorded alongside metrics
- Compare command produces valid output

---

### Phase 5: Advanced Eviction Policies

**Goal:** Implement ARC (Adaptive Replacement Cache) and InnoDB-style admission
control as described in `docs/tiered_graveyard.md`.

**What to build:**
- `src/ctx_rm/core/policies/arc.py` — Full ARC implementation with T1/T2 (recency/frequency) + B1/B2 ghost lists. Adaptive parameter `p` shifts balance based on ghost hits.
- `src/ctx_rm/core/policies/innodb.py` — InnoDB-style split LRU: new segments enter "old" sublist, promote to "new" only on re-access. Prevents one-time large reads from polluting active context.
- Update `WarmCache` to support ARC ghost list integration (record evictions in B1/B2)
- Update `ContextBus` to support admission control (route large tool outputs to Warm instead of Active)

**Key decisions:**
- ARC's `p` parameter starts at 0 and adapts based on B1/B2 hits (favor recency vs frequency)
- InnoDB's midpoint insertion: new segments start at position 3/8 from the "hot" end
- Admission control: segments with `source` matching `file_read:*` or `tool:*` and `token_count > threshold` go directly to Warm
- These are opt-in policies selectable via `--policy arc` or `--policy innodb`

**Tests needed:**
- ARC adapts `p` on ghost hits
- ARC balances recency vs frequency correctly
- InnoDB midpoint insertion works
- InnoDB promotes on re-access only
- Admission control routes large segments to Warm

---

### Phase 6: Comprehensive Test Suite & CI

**Goal:** Achieve high test coverage, add integration tests, and set up GitHub
Actions CI.

**What to build:**
- Integration tests for the full pipeline (with mock drivers)
- Async tests for the Watcher
- Property-based tests for eviction policies (hypothesis library)
- `tests/drivers/test_gemini.py` and `tests/drivers/test_claude.py` — Test JSON parsing with real response fixtures
- `.github/workflows/ci.yml` — Run tests + lint on push/PR
- `.github/workflows/bench.yml` — Run benchmarks on schedule (optional, manual trigger)
- Add `pytest-cov` configuration for coverage reporting

**Tests needed:**
- Watcher async tests (start, eviction cycle, stop)
- Driver JSON parsing with fixture data
- Full pipeline integration (task load → execute → evaluate)
- Edge cases: empty context, budget=0, recall from empty store
- Coverage target: 90%+

---

## GSD Phase-to-Work Mapping

When running `/gsd:new-milestone`, propose this roadmap:

| GSD Phase | ctx-rm Work | Dependencies | Parallelizable |
|-----------|-------------|--------------|----------------|
| Phase 1 | Task YAML Loader & Fixtures | None | — |
| Phase 2 | Embedding-Based Search | None | Yes (with Phase 1) |
| Phase 3 | LLM-Based Scorer | None | Yes (with Phase 1, 2) |
| Phase 4 | End-to-End Pipeline | Phase 1 | — |
| Phase 5 | Advanced Eviction Policies | None | Yes (with Phase 4) |
| Phase 6 | Test Suite & CI | All above | — |

**Parallel execution opportunities:**
- Phases 1, 2, 3 are independent and can be planned/executed in parallel
- Phase 4 depends on Phase 1 (needs the task loader)
- Phase 5 is independent of 1-4 (pure core engine work)
- Phase 6 is the final integration phase

---

## Context for GSD Discussion Phases

When running `/gsd:discuss-phase`, here are the key decisions already made:

### Architecture Decisions (Locked)
- **CLI-first**: Agents are driven via `gemini -p` and `claude -p` in headless mode. No SDK-based agents. Uses existing subscriptions (no API costs for agent execution).
- **Tiered storage**: Active → Warm → Cold → Graveyard → Zombie (see `docs/tiered_graveyard.md`)
- **Async background eviction**: The Watcher runs as `asyncio.create_task()`, never blocks the agent
- **Pluggable policies**: All eviction policies implement `EvictionPolicy` ABC
- **Pydantic models**: All data models use Pydantic v2
- **SQLite for persistence**: ColdStore uses SQLite, no external dependencies

### Tech Preferences (Locked)
- Python 3.12+, Astral `uv` for package management
- `structlog` for structured logging
- `orjson` for fast JSON serialization
- `typer` + `rich` for CLI
- `pytest` + `pytest-asyncio` for tests
- `ruff` for linting

### Open Questions (For Discussion)
- **Scoring prompt design**: What prompt should the LLM scorer use? How much context to include?
- **Fixture complexity**: Should fixtures be minimal (just the files needed) or realistic (full project structure)?
- **Benchmark task difficulty**: The 10 tasks in the YAML may need tuning after initial runs
- **Embedding model choice**: Sentence-transformers local vs Gemini API? Trade-off: latency vs quality

---

## Key Files to Read

Before planning any phase, read these files for full context:

| File | Why |
|------|-----|
| `README.md` | Project overview, architecture diagram, positioning |
| `docs/architecture.md` | System design, CLI driver architecture |
| `docs/tiered_graveyard.md` | OS/DB theory → tier design (LRU/CLOCK/ARC/2Q) |
| `docs/competitive_analysis.md` | How ctx-rm differs from MemAct, SWE-Pruner, ACON |
| `docs/context_removal_benchmark_tasks.yaml` | The 10 benchmark task definitions |
| `src/ctx_rm/core/bus.py` | Central coordinator (the heart of the system) |
| `src/ctx_rm/core/graveyard.py` | Tiered store implementation |
| `src/ctx_rm/benchmarks/runner.py` | Current benchmark runner (to be extended) |
| `src/ctx_rm/drivers/base.py` | Agent driver interface |
| `pyproject.toml` | Dependencies and project configuration |

---

## Success Criteria for Milestone 1

The milestone is complete when:

1. **`ctx-rm bench --task CR-001 --mode ctx-rm --driver gemini`** completes end-to-end: loads task, creates fixture, runs 20+ turns with needle injection and noise, evaluates success criteria, exports metrics
2. **All 3 modes** (minimal, ctx-rm, full) produce comparable results for at least 3 tasks
3. **`ctx-rm compare`** generates a table showing token usage, eviction stats, and task success across modes
4. **At least one task** demonstrates ctx-rm outperforming full-context (noise reduction tasks: CR-004, CR-005, CR-006)
5. **Test coverage ≥ 90%** with CI running on every push
6. **All 10 fixture repos** exist and are validated

---

## Future Milestones (Not Yet Planned)

### Milestone 2: "MCP Server & Agent Integration"
- Expose ctx-rm as an MCP server with tools: `score_context`, `evict_chunk`, `recall_chunk`, `search_graveyard`
- Agent skill file (.md) that teaches agents how to invoke ctx-rm
- Hook-based integration: `BeforeAgent` hook for Gemini CLI, `PostToolUse` hook for Claude Code
- Real-time `stream-json` monitoring

### Milestone 3: "Research Paper"
- Run full benchmark suite across all tasks × modes × drivers × policies
- Statistical analysis with confidence intervals
- Generate publication-quality charts (Apache ECharts or matplotlib)
- Write up findings as a research paper draft

### Milestone 4: "Production Packaging"
- `pip install ctx-rm` distribution
- PyPI publishing
- Docker image for isolated benchmarking
- GitHub Actions for automated benchmark runs
