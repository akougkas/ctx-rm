# ctx-rm

## What This Is

A context removal engine for LLM coding agents that applies OS virtual memory and database buffer pool concepts to manage context windows. It evicts low-value segments to a tiered graveyard (Warm/Cold/Zombie) and recalls them on demand, keeping agents focused on relevant context while staying within token budgets. Benchmarked against Gemini CLI and Claude Code in headless mode.

## Core Value

Prove that intelligent context eviction outperforms both no-history and full-history approaches for multi-turn coding tasks — measured by benchmark task success rate, token efficiency, and needle retention.

## Requirements

### Validated

- ✓ Segment model with 5-tier lifecycle (Active/Warm/Cold/Graveyard/Zombie), access tracking, eviction audit — existing
- ✓ ContextBus central coordinator: ingest, score, evict, recall, render, token budget enforcement — existing
- ✓ TieredStore with WarmCache (in-memory LRU), ColdStore (SQLite + keyword search), ZombieQueue (page-fault staging) — existing
- ✓ HeuristicScorer with exponential recency decay, log-scaled frequency, role weighting — existing
- ✓ Three eviction policies: LRU, CLOCK (PostgreSQL-style), BudgetAware (composite score + LRU fallback) — existing
- ✓ Async background eviction Watcher with 4 trigger modes (interval, threshold, per-turn, hybrid) — existing
- ✓ CLI drivers for Gemini and Claude via subprocess (headless JSON mode) — existing
- ✓ Telemetry: ingestion/eviction/recall events, per-turn snapshots, JSON export — existing
- ✓ Benchmark runner with 3 modes (Minimal, ctx-rm, Full) — existing
- ✓ CLI: `ctx-rm info`, `ctx-rm bench`, `ctx-rm compare` — existing
- ✓ 30 passing tests covering core engine, policies, tiered store — existing

### Active

- [ ] Task YAML loader: parse benchmark task definitions from YAML into executable multi-turn scenarios
- [ ] Fixture generator: 10 mini-codebase fixtures (CR-001 through CR-010) for benchmark tasks
- [ ] Task runner: turn-by-turn executor with needle injection and noise generation
- [ ] Evaluation engine: file_contains, file_not_contains, file_contains_in_order, file_equals assertions
- [ ] Embedding-based ColdStore search: vector similarity replacing keyword LIKE search
- [ ] LLM-based scorer: Gemini Flash Lite via google-genai SDK for segment relevance scoring
- [ ] End-to-end benchmark pipeline: `ctx-rm bench --task CR-001 --mode ctx-rm --driver gemini`
- [ ] Batch benchmark runner: `ctx-rm bench --all` for all tasks x modes x drivers
- [ ] Results comparison: `ctx-rm compare` generates summary tables from benchmark results
- [ ] ARC eviction policy: adaptive replacement cache with T1/T2 + B1/B2 ghost lists
- [ ] InnoDB-style admission control: split LRU with midpoint insertion for large reads
- [ ] Comprehensive test suite: 90%+ coverage with integration, async, and property-based tests
- [ ] CI pipeline: GitHub Actions for tests + lint on push/PR

### Out of Scope

- MCP server integration — deferred to Milestone 2
- Hook-based agent integration (BeforeAgent, PostToolUse) — deferred to Milestone 2
- Research paper / publication — deferred to Milestone 3
- PyPI packaging / `pip install ctx-rm` — deferred to Milestone 4
- Docker image — deferred to Milestone 4
- SDK-based agents — architecture is CLI-first by design, no API-driven agents

## Context

- Existing v0.1.0 codebase: 24 Python source files, 30 tests, full docs, working CLI
- 10 benchmark tasks defined in `docs/context_removal_benchmark_tasks.yaml` with needle injection, noise patterns, and success criteria
- Detailed theoretical foundation in `docs/tiered_graveyard.md` (LRU/LFU/CLOCK/ARC/2Q mapped to LLM context)
- Competitive analysis of MemAct, SWE-Pruner, ACON in `docs/competitive_analysis.md`
- Tech stack: Python 3.12+, uv, Pydantic v2, Typer, Rich, structlog, orjson, anyio, SQLite
- CLI drivers use existing user subscriptions (no API costs for agent execution)
- Gemini Flash Lite is the only API call (scoring) — essentially free

## Constraints

- **Tech stack**: Python 3.12+, uv, existing dependency set — locked from v0.1.0
- **CLI-first**: Agents driven via `gemini -p` and `claude -p` subprocess calls, not SDK agents
- **No API costs for agents**: Uses CLI subscriptions, only Gemini Flash Lite scoring uses API
- **SQLite only**: No external database dependencies for persistence
- **Pluggable**: All policies/scorers implement ABCs — new implementations must follow existing patterns

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| CLI-first driver model | Uses existing subscriptions, no API costs for agent execution | ✓ Good |
| Tiered storage (5 tiers) | Maps directly to OS/DB memory hierarchy theory | ✓ Good |
| SQLite for ColdStore | Zero-dependency persistence, embedded, sufficient for research | ✓ Good |
| Gemini Flash Lite for LLM scoring | Essentially free, fast, sufficient for relevance scoring | — Pending |
| Sentence hashing as default embedding | Zero ML dependency baseline, optional upgrade to sentence-transformers | — Pending |
| Fixtures as self-contained directories | Each benchmark task gets its own mini-repo, copied to temp for isolation | — Pending |

---
*Last updated: 2026-02-05 after initialization*
