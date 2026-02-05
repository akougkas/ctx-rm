# Architecture

**Analysis Date:** 2026-02-05

## Pattern Overview

**Overall:** Multi-tier memory management system inspired by OS virtual memory and database buffer pools

**Key Characteristics:**
- Event-driven segment lifecycle (Active → Warm → Cold → Graveyard → Zombie → Active)
- Background asynchronous eviction via Watcher (agent-agnostic, non-blocking)
- Pluggable scoring (heuristic or LLM-based) and eviction policies (LRU, CLOCK, Budget-aware)
- CLI-first driver model (subprocess invocation of Gemini CLI and Claude Code)
- Research-oriented metrics collection for benchmark analysis

## Layers

**Core Engine:**
- Purpose: Manages segment lifecycle, tier transitions, scoring, and eviction logic
- Location: `src/ctx_rm/core/`
- Contains: Segment model, ContextBus coordinator, TieredStore (Warm/Cold/Graveyard/Zombie), Scorer, Policies
- Depends on: Pydantic (models), structlog (logging), SQLite (cold/graveyard persistence), numpy (optional scoring)
- Used by: Benchmarks runner, Watcher, Telemetry, CLI

**Segment Model:**
- Purpose: Atomic unit of context (user message, assistant response, tool output, file read)
- Location: `src/ctx_rm/core/segment.py`
- Contains: Pydantic model with tier state, timestamps, access pattern tracking (recency, frequency, ref_bit), scoring metadata
- Depends on: Pydantic, time/uuid
- Used by: All core components

**ContextBus (Central Coordinator):**
- Purpose: Public API between external harness and internal eviction engine
- Location: `src/ctx_rm/core/bus.py`
- Contains: Active segment registry (OrderedDict), token budget enforcement, ingest/evict/recall operations, auto-eviction trigger
- Depends on: TieredStore, EvictionPolicy, Scorer, MetricsCollector
- Used by: BenchmarkRunner, Watcher

**TieredStore (Memory Hierarchy):**
- Purpose: Implements OS/DB-inspired tier transitions (Active → Warm → Cold → Graveyard)
- Location: `src/ctx_rm/core/graveyard.py`
- Contains: WarmCache (in-memory LRU), ColdStore (SQLite with search), ZombieQueue (recall staging)
- Depends on: SQLite, OrderedDict, deque, json
- Used by: ContextBus

**Scorer:**
- Purpose: Evaluates segment value for eviction decisions (composite score in [0, 1])
- Location: `src/ctx_rm/core/scorer.py`
- Contains: Scorer protocol (ABC), HeuristicScorer (recency exponential decay + frequency log-scale + role weights)
- Depends on: math, Segment
- Used by: ContextBus (called before eviction cycle)

**Policies:**
- Purpose: Eviction strategy (which segments to evict to meet token budget)
- Location: `src/ctx_rm/core/policies/`
- Contains: EvictionPolicy protocol, LRUPolicy, ClockPolicy (PostgreSQL-style ref_bit sweep), BudgetAwarePolicy (composite score ranking)
- Depends on: Segment
- Used by: ContextBus

**Watcher (Background Eviction):**
- Purpose: Async loop that monitors ContextBus and triggers eviction cycles based on threshold/interval/turn triggers
- Location: `src/ctx_rm/watch/watcher.py`
- Contains: Watcher async task, WatcherConfig (trigger modes: interval, threshold, turn, hybrid)
- Depends on: asyncio, ContextBus
- Used by: BenchmarkRunner (spawned as background task)

**Driver Layer:**
- Purpose: Wraps CLI agents (Gemini CLI, Claude Code) via subprocess, drives in headless mode
- Location: `src/ctx_rm/drivers/`
- Contains: AgentDriver protocol, GeminiCLIDriver, ClaudeCodeDriver (subprocess invocation with `-p --output-format json`)
- Depends on: asyncio.subprocess, json parsing
- Used by: BenchmarkRunner

**Telemetry:**
- Purpose: Research metrics collection (eviction events, recalls, snapshots, agent responses)
- Location: `src/ctx_rm/telemetry/metrics.py`
- Contains: MetricsCollector, event dataclasses (IngestEvent, EvictionEvent, RecallEvent, TurnSnapshot)
- Depends on: orjson, dataclasses
- Used by: ContextBus (event recording), BenchmarkRunner (export to JSON)

**Benchmark Orchestrator:**
- Purpose: Runs 3-mode experiments (Minimal, ctx-rm, Full) to compare context management strategies
- Location: `src/ctx_rm/benchmarks/runner.py`
- Contains: BenchmarkRunner, task loading (YAML stubs), turn-by-turn agent invocation, metrics export
- Depends on: All core components, drivers, telemetry, watch
- Used by: CLI (ctx-rm bench command)

**CLI:**
- Purpose: Typer-based command interface for running benchmarks and viewing system info
- Location: `src/ctx_rm/cli/main.py`
- Contains: Commands: `info` (check drivers), `bench` (run experiments), `compare` (compare results)
- Depends on: typer, rich, BenchmarkRunner
- Used by: End users (entry point: `ctx-rm`)

## Data Flow

**Ingest Flow (Normal Operation):**

1. BenchmarkRunner creates Segment from user prompt or agent response
2. ContextBus.ingest() adds segment to active context (OrderedDict), increments active_tokens
3. If active_tokens > headroom_target, ContextBus.run_eviction_cycle() triggers automatically
4. Scorer scores all non-pinned active segments (sets composite_score)
5. Policy selects segments to evict (returns ordered list)
6. ContextBus._evict_segment() removes from active, calls TieredStore.demote_to_warm()
7. TieredStore.WarmCache.put() adds to in-memory LRU, ages out to ColdStore if overflow
8. ColdStore.persist() writes to SQLite with full metadata

**Eviction Flow (Background Watcher):**

1. Watcher async loop checks trigger conditions (threshold, interval, turn)
2. If triggered, calls ContextBus.run_eviction_cycle()
3. (Same as steps 4-8 above)
4. MetricsCollector records EvictionEvent for each evicted segment

**Recall Flow (Page Fault Semantics):**

1. BenchmarkRunner or agent requests ContextBus.recall(seg_id)
2. TieredStore.recall() searches Warm (fast path) → Zombie (staged) → Cold (disk)
3. If found in Cold, stage through ZombieQueue (validation gate)
4. ZombieQueue.promote() returns segment to ContextBus
5. ContextBus adds back to active context (re-adds to OrderedDict, increments active_tokens)
6. MetricsCollector records RecallEvent

**Benchmark Turn Flow:**

1. BenchmarkRunner loads task turns (placeholder: 5 turns)
2. For each turn:
   - Advance turn counter (ContextBus.advance_turn())
   - Ingest user prompt as Segment
   - Render active segments to context string
   - Invoke driver (subprocess call to gemini/claude CLI with `-p --output-format json`)
   - Parse AgentResponse (text, tokens, tool_calls)
   - Ingest agent response as Segment
   - Take metrics snapshot (TurnSnapshot)
3. Export MetricsCollector to JSON

**State Management:**
- Active context: ContextBus maintains OrderedDict (insertion order preserved for rendering)
- Tier state: Each Segment.tier tracks current location (Active, Warm, Cold, Graveyard, Zombie)
- Access pattern: Segment.touch() updates last_accessed, access_count, ref_bit (for CLOCK)
- Token tracking: ContextBus._active_tokens incremented/decremented on ingest/evict

## Key Abstractions

**Segment:**
- Purpose: Universal context unit (message, file read, tool output)
- Examples: `src/ctx_rm/core/segment.py`
- Pattern: Pydantic model with lifecycle methods (touch, evict, recall)

**Tier:**
- Purpose: Memory hierarchy level (maps to OS/DB concepts)
- Examples: Tier.ACTIVE (buffer pool hot pages), Tier.WARM (OS page cache), Tier.COLD (disk pages), Tier.GRAVEYARD (WAL archive), Tier.ZOMBIE (page fault handler)
- Pattern: StrEnum with semantic mappings

**EvictionPolicy:**
- Purpose: Strategy pattern for selecting segments to evict
- Examples: `src/ctx_rm/core/policies/lru.py` (sorted by last_accessed), `src/ctx_rm/core/policies/clock.py` (ref_bit sweep), `src/ctx_rm/core/policies/budget.py` (composite_score ranking)
- Pattern: ABC with select_evictions() method

**Scorer:**
- Purpose: Pluggable scoring (heuristic or LLM-based)
- Examples: `src/ctx_rm/core/scorer.py` HeuristicScorer (recency exponential decay, frequency log-scale, role weights)
- Pattern: ABC with score_batch() method

**AgentDriver:**
- Purpose: Subprocess wrapper for CLI agents
- Examples: `src/ctx_rm/drivers/gemini.py`, `src/ctx_rm/drivers/claude.py`
- Pattern: ABC with async invoke() and check_available() methods

## Entry Points

**CLI Entry:**
- Location: `src/ctx_rm/cli/main.py`
- Triggers: `ctx-rm` command (typer app)
- Responsibilities: Parses CLI args, dispatches to BenchmarkRunner or info/compare commands

**BenchmarkRunner.run():**
- Location: `src/ctx_rm/benchmarks/runner.py`
- Triggers: `ctx-rm bench` command
- Responsibilities: Creates driver, ContextBus, Watcher; runs 3-mode experiment; exports metrics

**ContextBus.ingest():**
- Location: `src/ctx_rm/core/bus.py`
- Triggers: BenchmarkRunner ingests user/agent segments
- Responsibilities: Adds to active context, auto-triggers eviction if over budget

**Watcher.run():**
- Location: `src/ctx_rm/watch/watcher.py`
- Triggers: BenchmarkRunner spawns as asyncio task
- Responsibilities: Background loop that monitors ContextBus and triggers eviction cycles

## Error Handling

**Strategy:** Structured logging with fail-fast for configuration errors, graceful degradation for agent failures

**Patterns:**
- Driver unavailable: `check_available()` returns False, BenchmarkRunner logs error and exits
- Agent subprocess failure: AgentResponse.success = False, error message captured, BenchmarkRunner continues
- Eviction overflow: TieredStore ages out Warm → Cold → Graveyard (no data loss)
- Recall miss: TieredStore.recall() returns None, ContextBus logs warning, caller handles
- Watcher exception: try/except in Watcher.run() loop, logs exception and sleeps (continues)
- SQLite errors: Propagate (fail-fast) — indicates configuration or disk issue

## Cross-Cutting Concerns

**Logging:** structlog with structured JSON output (logger.info/debug/warning/error with key=value pairs)

**Validation:** Pydantic models enforce schema (Segment, WatcherConfig, AgentResponse); no runtime validation beyond model __init__

**Authentication:** Not handled by ctx-rm (relies on installed CLI agents: `gemini` and `claude` must be authenticated externally)

---

*Architecture analysis: 2026-02-05*
