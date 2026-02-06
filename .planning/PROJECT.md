# ctx-rm

## What This Is

A context removal engine for LLM coding agents that applies OS virtual memory and database buffer pool concepts to manage context windows. It evicts low-value segments to a tiered graveyard (Warm/Cold/Zombie) and recalls them on demand, keeping agents focused on relevant context while staying within token budgets. Includes a complete benchmark system with task loading, embedding-based search, LLM scoring, and end-to-end pipeline for evaluating eviction strategies. Benchmarked against Gemini CLI and Claude Code in headless mode.

## Core Value

Prove that intelligent context eviction outperforms both no-history and full-history approaches for multi-turn coding tasks — measured by benchmark task success rate, token efficiency, and needle retention.

## Requirements

### Validated

- ✓ Segment model with 5-tier lifecycle, access tracking, eviction audit — v0.1.0
- ✓ ContextBus central coordinator: ingest, score, evict, recall, render, token budget enforcement — v0.1.0
- ✓ TieredStore with WarmCache, ColdStore (SQLite + embedding search), ZombieQueue — v0.1.0 + v1.0
- ✓ HeuristicScorer with exponential recency decay, log-scaled frequency, role weighting — v0.1.0
- ✓ Three eviction policies: LRU, CLOCK, BudgetAware — v0.1.0
- ✓ Async background eviction Watcher with 4 trigger modes — v0.1.0
- ✓ CLI drivers for Gemini and Claude via subprocess — v0.1.0
- ✓ Telemetry: ingestion/eviction/recall events, per-turn snapshots, JSON export — v0.1.0
- ✓ Benchmark runner with 3 modes (Minimal, ctx-rm, Full) — v0.1.0
- ✓ CLI: `ctx-rm info`, `ctx-rm bench`, `ctx-rm compare`, `ctx-rm tasks` — v0.1.0 + v1.0
- ✓ Task YAML loader: parse benchmark tasks from YAML into executable multi-turn scenarios — v1.0
- ✓ Fixture generator: 10 mini-codebase fixtures (CR-001 through CR-010) — v1.0
- ✓ Task runner: turn-by-turn executor with needle injection and noise generation — v1.0
- ✓ Evaluation engine: file_contains, file_not_contains, file_contains_in_order, file_equals assertions — v1.0
- ✓ Embedding-based ColdStore search: vector similarity with cosine ranking and keyword fallback — v1.0
- ✓ OllamaScorer: local LLM scoring with dynamic model discovery, caching, batch concurrency — v1.0
- ✓ End-to-end benchmark pipeline: `ctx-rm bench --task --mode --driver --policy` — v1.0
- ✓ Batch benchmark runner: `ctx-rm bench --all` for all tasks x modes x drivers — v1.0
- ✓ Results comparison: `ctx-rm compare` with nested results and mode-aggregated summary — v1.0
- ✓ ARC eviction policy with T1/T2 lists, B1/B2 ghost lists, adaptive parameter p — v1.0
- ✓ InnoDB-style split LRU with midpoint insertion and re-access promotion — v1.0
- ✓ Admission control: routes large tool outputs to Warm bypassing Active — v1.0
- ✓ 128 tests passing across all subsystems — v1.0

## Current Milestone: v1.1 Pipeline Validation

**Goal:** Run a real benchmark task end-to-end with Gemini CLI across all 3 modes and 5 eviction policies, fixing whatever breaks until the pipeline is stable.

**Target features:**
- Dry-run validation of pipeline without real agent calls
- Single end-to-end run with real Gemini CLI
- Full matrix: CR-001 × 3 modes × 5 policies with Gemini
- Fix all bugs surfaced during real execution
- Watcher stop() race condition fix (asyncio.Event)

### Active

- [ ] Dry-run pipeline validation (mock driver, real task/fixtures/evaluator)
- [ ] Single real benchmark run: CR-001, ctx-rm mode, LRU policy, Gemini CLI
- [ ] Full matrix: CR-001 × minimal/ctx-rm/full × all 5 policies × Gemini
- [ ] Fix Watcher stop() race condition with asyncio.Event
- [ ] Fix all pipeline bugs surfaced during real runs

### Out of Scope

- MCP server integration — deferred to Milestone 2
- Hook-based agent integration (BeforeAgent, PostToolUse) — deferred to Milestone 2
- PyPI packaging / `pip install ctx-rm` — deferred to Milestone 4
- Docker image — deferred to Milestone 4
- SDK-based agents — architecture is CLI-first by design
- GitHub Actions CI — deferred to v1.2
- pytest-cov / coverage targets — deferred to v1.2
- Property-based tests (hypothesis) — deferred to v1.2
- Statistical analysis / publication charts — deferred to v1.2 (need multi-task data first)
- Multiple drivers (Claude CLI) — deferred to v1.2 (validate with Gemini first)
- Multiple benchmark tasks — deferred to v1.2 (validate CR-001 first)

## Context

Shipped v1.0 with 6,424 LOC Python across 35 files.
Tech stack: Python 3.12+, uv, Pydantic v2, Typer, Rich, structlog, orjson, anyio, SQLite, PyYAML, Ollama.
128 tests passing. 5 eviction policies (LRU, CLOCK, BudgetAware, ARC, InnoDB).
10 benchmark tasks with fixture directories and evaluation assertions.
Embedding search via feature hashing (default) or sentence-transformers (optional).

## Constraints

- **Tech stack**: Python 3.12+, uv, existing dependency set
- **CLI-first**: Agents driven via `gemini -p` and `claude -p` subprocess calls, not SDK agents
- **No API costs for agents**: Uses CLI subscriptions, only Ollama scoring is local
- **SQLite only**: No external database dependencies for persistence
- **Pluggable**: All policies/scorers/embeddings implement ABCs

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| CLI-first driver model | Uses existing subscriptions, no API costs for agent execution | ✓ Good |
| Tiered storage (5 tiers) | Maps directly to OS/DB memory hierarchy theory | ✓ Good |
| SQLite for ColdStore | Zero-dependency persistence, embedded, sufficient for research | ✓ Good |
| Ollama for LLM scoring | Local, dynamic model discovery, no API costs | ✓ Good |
| Sentence hashing as default embedding | Zero ML dependency baseline, optional upgrade to sentence-transformers | ✓ Good |
| Fixtures as self-contained directories | Each benchmark task gets its own mini-repo, copied to temp for isolation | ✓ Good |
| file_equals as substring containment | Field name and content indicate "must preserve", not exact file match | ✓ Good |
| ARC ghost lists metadata-only | Matches ARC paper: ghosts track metadata for adaptation without memory overhead | ✓ Good |
| InnoDB old_pct=37 default | Matches MySQL InnoDB buffer pool midpoint (3/8 = 37.5%) | ✓ Good |
| select_evictions read-only | Separation between selection and mutation (on_evict sole mutator) | ✓ Good |
| Admission control source prefix matching | Source field uses prefix:detail format throughout codebase | ✓ Good |

---
*Last updated: 2026-02-06 after v1.1 milestone start*
