# ctx-rm

**Context Removal for LLM Agents** — let the agent ingest freely while a background engine evicts low-value content and stores it for recoverable recall.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-30%20passing-brightgreen.svg)]()

---

## The Problem

LLM coding agents like [Gemini CLI](https://github.com/google-gemini/gemini-cli) and [Claude Code](https://code.claude.com/docs) operate within a context window — 1M tokens for Gemini, 200K for Claude. In long sessions, context fills up. The industry has two responses:

| Approach | How it works | Limitation |
|----------|-------------|------------|
| **Context Curation** | Carefully gate what enters context | Requires upfront decisions about relevance — hard for open-ended tasks |
| **Context Compaction** | Summarize/compress to fit a budget | Lossy — summaries drop details that matter later |

**ctx-rm** explores a third path: **Context Removal**.

> Ingest anything. A background engine scores, evicts, and stores content from the active context. Evicted content is preserved whole and can be recalled on demand. Think of it as **virtual memory for LLM context** — page-in/page-out semantics with full recoverability.

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Benchmark Harness                        │
│   Drives agents in headless mode (-p --output-format json)  │
└────────────┬───────────────────────────────────┬────────────┘
             │                                   │
    ┌────────▼────────┐                ┌─────────▼─────────┐
    │  Gemini CLI      │                │  Claude Code       │
    │  gemini -p ...   │                │  claude -p ...     │
    └────────▲────────┘                └─────────▲─────────┘
             │                                   │
             └───────────────┬───────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Context Bus    │  ← Central coordinator
                    │   (ContextBus)   │
                    └──┬────┬────┬────┘
                       │    │    │
              ┌────────┘    │    └────────┐
              ▼             ▼             ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  Scorer   │ │ Evictor  │ │ Watcher  │
        │(heuristic │ │(LRU/CLOCK│ │ (async   │
        │ or LLM)   │ │/Budget)  │ │  loop)   │
        └──────────┘ └────┬─────┘ └──────────┘
                          │
                ┌─────────▼──────────┐
                │   Tiered Store      │
                │                     │
                │ Active ──▶ Warm     │  (in-memory LRU cache)
                │ Warm   ──▶ Cold     │  (SQLite persistent store)
                │ Cold   ──▶ Graveyard│  (archived, immutable)
                │                     │
                │ Cold/Graveyard ──▶ Zombie ──▶ Active  │  (recall)
                └─────────────────────┘
```

### Tier System (OS Virtual Memory Mapping)

| Tier | Analogy | Location | Description |
|------|---------|----------|-------------|
| **Active** | Buffer pool hot pages | In LLM context | Sent to the model each turn |
| **Warm** | OS page cache / ARC ghost | In-memory cache | Recently evicted, fast recall |
| **Cold** | Database disk pages | SQLite | Persistent, searchable, indexed |
| **Graveyard** | WAL archive / cold storage | SQLite (archived) | Append-only, compressed |
| **Zombie** | Page fault handler | Staging queue | Recalled content awaiting validation |

See [docs/tiered_graveyard.md](docs/tiered_graveyard.md) for the theoretical foundation (LRU, LFU, CLOCK, ARC, 2Q mappings).

---

## Key Design Decisions

1. **CLI-first, not SDK**: ctx-rm drives [Gemini CLI](https://github.com/google-gemini/gemini-cli) and [Claude Code](https://code.claude.com/docs/en/cli-reference) in headless mode (`-p --output-format json`). This uses your existing subscriptions — no API costs.

2. **Background, not inline**: The Watcher runs as an async task. The primary agent is never interrupted or aware of eviction.

3. **Removal, not compression**: Segments are evicted whole (recoverable), not summarized (lossy). The Graveyard preserves exact content.

4. **Separation of concerns**: The Scorer/Evictor is a separate process from the task agent. Two different "brains."

5. **Pluggable policies**: LRU, CLOCK (PostgreSQL-style), Budget-aware (score-based). Compose and swap freely.

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/akougkas/ctx-rm.git
cd ctx-rm
uv sync --all-extras

# Check available drivers
uv run ctx-rm info

# Run a benchmark (Gemini CLI, ctx-rm mode)
uv run ctx-rm bench gemini --mode ctx-rm --budget 100000 --policy budget

# Run the same task with full context (baseline)
uv run ctx-rm bench gemini --mode full

# Run with minimal context
uv run ctx-rm bench gemini --mode minimal

# Compare results
uv run ctx-rm compare ./results/
```

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`npm install -g @google/gemini-cli`) — free tier or Ultra subscription
- [Claude Code](https://code.claude.com/docs/en/quickstart) (`npm install -g @anthropic-ai/claude-code`) — Max subscription

---

## Benchmark Design

Three session modes, same task set:

| Mode | Strategy | What it tests |
|------|----------|--------------|
| **A: Minimal** | Only current turn prompt, no history | Lower bound on quality, upper bound on efficiency |
| **B: ctx-rm** | Greedy ingest + background removal + recoverable recall | The hypothesis: removal can match full-context quality at minimal-context cost |
| **C: Full** | Accumulate everything, no management | Upper bound on quality, lower bound on efficiency |

### Metrics Captured

- Total tokens ingested / evicted / recalled
- Peak and average context utilization
- Eviction/recall counts and hit rates
- Agent response quality (task success)
- Per-turn snapshots for time-series analysis

Results export to JSON for analysis in Jupyter notebooks.

---

## Positioning

```
               ┌──────────────────────────────────────────────────┐
               │              Context Management                   │
               └──────────────────────────────────────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        ▼                              ▼                              ▼
  ┌──────────────┐             ┌──────────────┐             ┌──────────────┐
  │  Curation    │             │  Compaction   │             │   Removal    │
  │  (gatekeep)  │             │  (summarize)  │             │  (evict)     │
  └──────────────┘             └──────────────┘             └──────────────┘
  LLMLingua,                   Claude Code's                  ctx-rm
  Selective Context,           auto-compact,                  (this project)
  LangChain CE                 ACON, CSIM
```

### Closest Prior Art

| Project | Relationship to ctx-rm |
|---------|----------------------|
| [MemAct](https://github.com/YuxiangZhang0114/MemAct) | Treats memory as learnable action (RL). ctx-rm is background + agent-agnostic |
| [SWE-Pruner](https://github.com/Ayanami1314/swe-pruner) | Code-specific pruning (inline). ctx-rm is async + multi-content-type |
| [ACON](https://github.com/microsoft/acon) | Compression guideline optimization. ctx-rm evicts (recoverable) vs compresses (lossy) |
| Claude Code compact | 3-tier summarization. ctx-rm preserves originals in graveyard |

See [docs/competitive_analysis.md](docs/competitive_analysis.md) for detailed comparisons.

---

## Project Structure

```
ctx-rm/
├── pyproject.toml                    # uv project, all dependencies
├── src/ctx_rm/
│   ├── core/
│   │   ├── segment.py                # Segment model (atomic context unit)
│   │   ├── bus.py                    # ContextBus (central coordinator)
│   │   ├── graveyard.py              # TieredStore (Warm/Cold/Graveyard/Zombie)
│   │   ├── scorer.py                 # Heuristic + pluggable LLM scorer
│   │   └── policies/                 # LRU, CLOCK, BudgetAware eviction
│   ├── watch/
│   │   └── watcher.py                # Async background eviction loop
│   ├── drivers/
│   │   ├── gemini.py                 # Gemini CLI subprocess driver
│   │   └── claude.py                 # Claude Code subprocess driver
│   ├── telemetry/
│   │   └── metrics.py                # Research metrics collector
│   ├── benchmarks/
│   │   └── runner.py                 # 3-mode benchmark orchestrator
│   ├── cli/
│   │   └── main.py                   # Typer CLI (ctx-rm command)
│   └── config.py                     # Pydantic settings
├── tests/                            # 30 tests, all passing
├── docs/
│   ├── architecture.md               # System design
│   ├── tiered_graveyard.md           # OS/DB theory → LLM context mapping
│   ├── competitive_analysis.md       # MemAct / SWE-Pruner / ACON analysis
│   ├── landscape.md                  # Research landscape and bibliography
│   └── context_removal_benchmark_tasks.yaml  # 10 benchmark task definitions
└── benchmarks/                       # Task fixtures (TODO)
```

---

## Research Context

ctx-rm is an experimental research project exploring whether **background context removal with recoverability** can match full-context quality at a fraction of the token cost.

### Key Hypothesis

> An LLM coding agent that ingests context freely while a background removal engine manages the active window will achieve comparable task success to a full-context agent, at significantly lower token cost — and will outperform both on tasks where noise degrades performance.

### Bibliography

See [docs/landscape.md](docs/landscape.md) for the full bibliography including:
- LLMLingua family (EMNLP'23, ACL'24)
- MemGPT/Letta, Mem0, Zep (agent memory systems)
- SWE-Pruner, MemAct, ACON (2025 context management)
- LongBench v1/v2 (evaluation benchmarks)

---

## License

Apache-2.0 — see [LICENSE](LICENSE).
