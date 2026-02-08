# NEXT-STEPS: ctx-rm Development Roadmap

> **This document is the handoff prompt for the next Claude Code session(s).**
> Read `SESSION-NEXT.md` first — it has the immediate next task.

---

## Current State (v0.3-dev)

### What Works

ctx-rm has a working autonomous agent that talks to llama-server over HTTP,
manages its own context window with tiered eviction, and can recall evicted
segments via page-fault semantics. The full feedback→adaptive→scoring→eviction
pipeline is built and integration-tested.

**First real benchmark proof (SPEC-001 on Nemotron-3-Nano-30B):**

| Mode | Result | Prompt Tokens | Turns | Evictions |
|------|--------|--------------|-------|-----------|
| **ctx-rm** | **PASS 2/2** | **7,151** | 6 | 1 |
| full | PASS 2/2 | 16,707 | 7 | 0 |
| minimal | PASS 2/2 | 11,586 | 9 | 0 |

ctx-rm passed with 57% fewer prompt tokens than full mode. The eviction engine
stripped noise, kept the needle, and the agent finished faster with cleaner context.

### Architecture: AgentLoop + LlamaCpp (only path)

```
AgentLoop (autonomous, tool-calling)
  → LlamaCppDriver (HTTP to llama-server, retry, JSON recovery)
    → ContextBus (ingest, score, evict, recall, admission control)
      → Scorer (Heuristic or Sequential, task-conditioned)
      → Policy (LRU / CLOCK / BudgetAware / ARC / InnoDB)
      → FeedbackTracker (eviction/recall/eval events)
      → AdaptiveWeights (source weights, headroom, policy params)
      → TieredStore (Warm → Cold → Graveyard → Zombie recall)
```

### What's Built

**Core Engine** (`src/ctx_rm/core/`):
- `segment.py` — Pydantic Segment model, 5-tier state, access tracking, eviction audit
- `bus.py` — ContextBus: ingest, score, evict, recall, admission control, feedback hooks, adaptive refresh, event callbacks
- `graveyard.py` — TieredStore: WarmCache (in-memory LRU), ColdStore (SQLite + embeddings), ZombieQueue
- `scorer.py` — HeuristicScorer (recency + frequency + role + source weighting)
- `scorer_sequential.py` — SequentialScorer: task-conditioned marginal value scoring with pluggable LLM backend, cache, fallback to Heuristic
- `adaptive.py` — AdaptiveWeights: source weight boosting/decay, headroom shifting, policy param tuning based on recall rate
- `feedback.py` — FeedbackTracker: bounded event log for eviction/recall/re-eviction/eval outcomes
- `tokenizer.py` — tiktoken cl100k_base with char/4 fallback
- `embedding.py` — HashingEmbeddingProvider (zero ML deps), optional SentenceTransformerProvider
- `policies/` — 5 policies: LRU, CLOCK, BudgetAware, ARC, InnoDB

**Agent** (`src/ctx_rm/agents/`):
- `loop.py` — AgentLoop: autonomous tool-calling agent with pair integrity, recall, watcher, progress event callbacks
- `tools.py` — 6 sandboxed tools (file_read, file_write, file_patch, run_shell, list_directory, grep_search)

**Driver** (`src/ctx_rm/drivers/`):
- `llamacpp.py` — HTTP driver for llama-server: retry with exponential backoff, context window discovery, 7-strategy JSON recovery for malformed tool arguments

**Benchmarks** (`src/ctx_rm/benchmarks/`):
- `runner.py` — BenchmarkRunner: 3 modes (minimal/ctx-rm/full), configurable policy/scorer/budget/batch-mode, event callback wiring for TUI
- `loader.py` + `models.py` — YAML task loader → validated Pydantic models
- `executor.py` — Turn builder with needle/noise injection
- `evaluator.py` — 4 assertion types (file_contains, file_not_contains, file_contains_in_order, file_equals)
- `fixtures.py` — Fixture directory isolation

**Integrations** (`src/ctx_rm/integrations/`):
- `ollama_scorer.py` — LLM scoring via local Ollama
- `llm_scoring_backend.py` — Pluggable LLM scoring helpers for SequentialScorer
- `sentence_transformers.py` — Optional embedding provider

**CLI** (`src/ctx_rm/cli/`):
- `main.py` — `ctx-rm info` / `tasks` / `bench` / `compare`
- `tui.py` — Live TUI dashboard (--live flag) + post-run Rich summary panel

**CLI flags**: `--mode`, `--policy`, `--scorer`, `--budget`, `--batch-mode`, `--max-turns`, `--enable-recall`, `--live`, `--all`

**13 benchmark tasks**: CR-001 through CR-010 + MULTI-001, TRACE-001, SPEC-001

**108 tests** across 6 files, all passing:
- `tests/agents/test_loop.py` (15 tests) — AgentLoop, recall, pair integrity, message ordering
- `tests/core/test_bus.py` (15 tests) — ContextBus, admission control, eviction, recall, batch modes
- `tests/core/test_graveyard.py` (20 tests) — TieredStore, WarmCache, ColdStore, ZombieQueue
- `tests/core/test_scorer_sequential.py` (18 tests) — SequentialScorer, cache, fallback, conditioning
- `tests/integration/test_pipeline_e2e.py` (17 tests) — full feedback→adaptive→scoring→eviction pipeline
- `tests/test_harness.py` (23 tests) — consolidated harness: modes, policies, scorers, YAML configs, events

---

## Milestone 1: "Benchmark Validation" — DONE

Sessions 1-8 built the engine, agent, driver, tasks, and first benchmark results.

- Phase 9: CI & Coverage — SCAFFOLDED (`.github/`, `.pre-commit-config.yaml` exist, not yet wired)

---

## Milestone 2: "Sequential Scoring" — IN PROGRESS

> Inspired by "Sequential Attention for Feature Selection" (Yasuda et al., ICLR 2023)

### Research Claims (Cascading)

1. **Conditional > Independent**: SequentialScorer outperforms HeuristicScorer
2. **Adaptive > Static**: Feedback-driven adaptation reduces page faults
3. **Full Pipeline**: ctx-rm matches full-context quality at a fraction of token cost

### Phase Status

- ~~Phase 1: SequentialScorer~~ — DONE
- Phase 2: Adaptive Batch Eviction — DONE (code built). Needs real benchmark validation under pressure.
- ~~Phase 3: Three-Layer Learning Loop~~ — DONE
- ~~Phase 4: Event Callbacks + TUI~~ — DONE. ContextBus and AgentLoop fire event callbacks; TuiDashboard renders live; post-run Rich summary.
- ~~Phase 5: Consolidated Test Harness~~ — DONE. test_harness.py + YAML configs replace 22 deleted test files.
- ~~Phase 6: Legacy Cleanup~~ — DONE. Deleted gemini.py, claude.py, base.py, mock.py, experiment_harness.py, experiment_loader.py, experiment CLI command.

### What's Left for Milestone 2

1. **Budget calibration** — current tasks don't generate enough context to trigger eviction at default 100K budget. Need to either increase noise injection or calibrate per-task budgets so eviction actually fires.
2. **Multi-run statistical experiments** — run each task N times per config, compute CIs, produce comparison tables proving the three cascading claims.
3. **SequentialScorer with real LLM backend** — test with Ollama scorer, not just lexical backend.

---

## What's Rough / Missing

- No CI pipeline running yet (scaffolded only)
- README still has some stale sections (extending ctx-rm examples could be tighter)
- No response_log.jsonl being written per-run (evaluation.json + metrics.json are written)
- Budget calibration is the real blocker for meaningful experiments — 100K default is too large for current task sizes
- pyproject.toml version is 0.1.0 but docs say v0.3-dev

---

## Architecture Decisions (Locked)

- **Own agent**: AgentLoop drives llama-server via HTTP. No subprocess CLI shelling.
- **Tiered storage**: Active → Warm → Cold → Graveyard → Zombie
- **Async background eviction**: Watcher runs as `asyncio.create_task()`
- **Pluggable everything**: Policies, scorers, embedding providers implement ABCs
- **Two brains**: Task agent and scoring brain are separate. Scorer defaults to cheap model.
- **Recall source filter**: Only recall needle/context/user_task/user_message. Never recall assistant_tool_call or tool (pair integrity).
- **Adaptive batch eviction**: `--batch-mode adaptive` for one-at-a-time near budget
- **SequentialScorer** is a separate class from HeuristicScorer for clean A/B comparison
- **Pydantic v2** for data models, **SQLite** for persistence, no external deps
- **Event callbacks** on ContextBus + AgentLoop for live TUI and telemetry

## Tech Stack

- Python 3.12+, `uv` for packages
- `structlog`, `orjson`, `typer` + `rich`, `pytest` + `pytest-asyncio`, `ruff`
- llama-server on mini:8080 (Nemotron-3-Nano-30B)

---

## Key Files to Read

| File | Why |
|------|-----|
| `src/ctx_rm/core/bus.py` | Central coordinator — all paths flow through here |
| `src/ctx_rm/core/scorer_sequential.py` | Task-conditioned scoring (M2 core) |
| `src/ctx_rm/core/adaptive.py` | Feedback-driven adaptation (M2 core) |
| `src/ctx_rm/core/feedback.py` | Event tracking for adaptation |
| `src/ctx_rm/agents/loop.py` | Agent loop with recall and pair integrity |
| `src/ctx_rm/drivers/llamacpp.py` | HTTP driver with retry and JSON recovery |
| `src/ctx_rm/benchmarks/runner.py` | BenchmarkRunner — 3 modes |
| `src/ctx_rm/cli/tui.py` | Live TUI dashboard + post-run summary |
| `tests/test_harness.py` | Consolidated test harness (YAML-configurable) |
| `tests/integration/test_pipeline_e2e.py` | 17 tests proving the full pipeline |

---

## Future Milestones

### Milestone 3: "MCP Server & Agent Integration"
- Expose ctx-rm as an MCP server
- Hook-based integration for external agents

### Milestone 4: "Research Paper" (IEEE SC 2026 target)
- Full benchmark suite with statistical validation
- Three cascading experiments
- Publication-quality charts and analysis

### Milestone 5: "Production Packaging"
- `pip install ctx-rm`, PyPI, Docker
