# ctx-rm

**Context Removal for LLM Agents** — a background engine that scores, evicts, and stores low-value context segments while preserving them for on-demand recall. Virtual memory semantics for LLM context windows.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-171%20passing-brightgreen.svg)]()
[![v0.4](https://img.shields.io/badge/version-0.4--dev-orange.svg)]()

---

## Table of Contents

- [The Problem](#the-problem)
- [How ctx-rm Works](#how-ctx-rm-works)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Eviction Policies](#eviction-policies)
- [Benchmark System](#benchmark-system)
- [Project Structure](#project-structure)
- [Extending ctx-rm](#extending-ctx-rm)
- [Research Context](#research-context)
- [License](#license)

---

## The Problem

LLM coding agents like [Gemini CLI](https://github.com/google-gemini/gemini-cli) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) operate within a context window — 1M tokens for Gemini, 200K for Claude. In long multi-turn sessions, context fills up. The industry has two responses:

| Approach | How it works | Limitation |
|----------|-------------|------------|
| **Context Curation** | Carefully gate what enters context | Requires upfront decisions about relevance — hard for open-ended tasks |
| **Context Compaction** | Summarize/compress to fit a budget | Lossy — summaries drop details that matter later |

**ctx-rm** explores a third path: **Context Removal**.

> Ingest anything. A background engine scores, evicts, and stores content from the active context. Evicted content is preserved whole and can be recalled on demand. Think of it as **virtual memory for LLM context** — page-in/page-out semantics with full recoverability.

The key insight: OS virtual memory and database buffer pools have solved this problem for decades. A page fault in Linux retrieves the exact page — no information loss. ctx-rm applies the same principle to LLM context.

---

## How ctx-rm Works

### The Segment Lifecycle

Every piece of content entering the context window becomes a **Segment** — the atomic unit, analogous to a page in virtual memory. Each segment tracks:

- **Content and role** (system, user, assistant, tool)
- **Token count** (for budget enforcement)
- **Access pattern** (creation time, last accessed, access count)
- **Scoring metadata** (relevance, staleness, redundancy, composite score)
- **Tier** (where the segment currently lives)
- **Pin state** (pinned segments are never evicted)

Segments flow through five tiers:

```
Ingest → Active → Warm → Cold → Graveyard
                                     ↓
            Active ← Zombie ← Cold/Graveyard   (recall = page fault)
```

### The Eviction Cycle

1. **Ingest**: New content enters Active. The ContextBus assigns a turn number, checks admission control (large tool outputs may bypass Active and go directly to Warm), and notifies the eviction policy via `on_ingest()`.

2. **Score**: The Scorer evaluates each segment's value. Two scorers are available:
   - **HeuristicScorer**: Combines recency (exponential decay), frequency (log-scaled access count), role weight, and source weight. Fast, no external dependencies.
   - **SequentialScorer**: Task-conditioned marginal value scoring — evaluates each segment's importance relative to the retained set AND the current task goal. Falls back to HeuristicScorer on failure. Supports pluggable LLM backends (Ollama, generic HTTP) or a built-in lexical backend.

3. **Evict**: When the active context exceeds the token budget (minus a configurable headroom), the eviction policy selects segments to remove. Supports fixed batch eviction or adaptive mode (one-at-a-time near budget, batch when far over). Evicted segments move to Warm → Cold → Graveyard.

4. **Recall**: When the agent needs evicted content, a search against Warm+Cold returns matching segments. They promote back to Active via the Zombie staging tier. Source filtering ensures only safe sources are recalled (needle, context, user_task, user_message) — never assistant/tool pairs (pair integrity).

5. **Adapt**: The `FeedbackTracker` records eviction/recall/eval events. `AdaptiveWeights` uses this feedback to shift scoring behavior: high recall rate → conservative (boost source weights, increase headroom), zero recall rate → aggressive (decay weights, shrink headroom). This mirrors ARC's adaptive `p` parameter generalized across the full pipeline.

### Admission Control

Not all content deserves Active tier placement. Segments from `file_read` and `tool` sources above a configurable token threshold (default: 2,000 tokens) bypass Active entirely and go directly to Warm. This prevents large file reads from evicting more valuable conversational context — the same principle as InnoDB's midpoint insertion protecting the buffer pool hot pages from full table scans.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Benchmark Harness                              │
│   BenchmarkRunner → TaskLoader → Evaluator                       │
│   test_harness.py (YAML-configurable tests + A/B experiments)    │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                     ┌─────────▼──────────┐
                     │     AgentLoop       │
                     │ (autonomous agent)  │
                     │  tools + ContextBus │
                     └─────────┬───────────┘
                               │
               ┌───────────────▼──────────────────────────┐
               │   LlamaCpp Driver (HTTP)                   │
               │   /v1/chat/completions, retry, JSON recov. │
               │   context window discovery                 │
               └───────────────┬──────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│   ContextBus  ← Central coordinator                  │
│   ingest, score, evict, recall, admission control    │
│   feedback tracking, adaptive weight refresh         │
└──┬────────┬────────┬──────────┬────────┬────────────┘
   │        │        │          │        │
   ▼        ▼        ▼          ▼        ▼
┌───────┐┌───────┐┌───────┐┌────────┐┌──────────┐
│Scorer ││Policy ││Watcher││Feedback││ Adaptive │
│Heuris.││LRU/   ││Async  ││Tracker ││ Weights  │
│Sequen.││CLOCK/ ││bg     ││events  ││ source/  │
│Ollama ││Budget/││evict  ││recall  ││ policy   │
│       ││ARC/   ││loop   ││eval    ││ params   │
│       ││InnoDB ││       ││churn   ││          │
└───────┘└──┬────┘└───────┘└────────┘└──────────┘
            │
 ┌──────────▼──────────┐
 │   Tiered Store       │
 │                      │
 │ Active ──▶ Warm      │  (in-memory LRU cache)
 │ Warm   ──▶ Cold      │  (SQLite + embeddings)
 │ Cold   ──▶ Graveyard │  (archived, immutable)
 │                      │
 │ Warm/Cold ──▶ Zombie ──▶ Active  (recall)
 └──────────────────────┘
```

### Tier System

| Tier | OS/DB Analogy | Storage | Description |
|------|---------------|---------|-------------|
| **Active** | Buffer pool hot pages | In LLM context | Sent to the model each turn |
| **Warm** | Page cache / ARC ghost list | In-memory LRU | Recently evicted, fast recall (no I/O) |
| **Cold** | Database disk pages | SQLite + embeddings | Persistent, searchable by vector similarity or keyword |
| **Graveyard** | WAL archive / cold storage | SQLite (archived) | Append-only, compressed, immutable |
| **Zombie** | Page fault handler | Staging queue | Recalled content awaiting validation before re-entry |

See [docs/tiered_graveyard.md](docs/tiered_graveyard.md) for the full theoretical foundation mapping LRU, LFU, CLOCK, ARC, and 2Q to LLM context management.

---

## Quick Start

### Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/)
- **llama-server** running locally or on the network (Nemotron-3-Nano-30B recommended)
- **Optional:** [Ollama](https://ollama.ai/) for LLM-based scoring (any model works — auto-discovered)

### Install

```bash
git clone https://github.com/akougkas/ctx-rm.git
cd ctx-rm
uv sync --all-extras
```

### Verify

```bash
# Check system status, available drivers, policies, and tasks
uv run ctx-rm info

# List all 16 benchmark tasks
uv run ctx-rm tasks
```

### Run Your First Benchmark

```bash
# Single task — ctx-rm mode with BudgetAware policy
uv run ctx-rm bench --task CR-001 --mode ctx-rm --policy budget

# Full context baseline (no eviction)
uv run ctx-rm bench --task CR-001 --mode full

# Minimal context baseline (no history)
uv run ctx-rm bench --task CR-001 --mode minimal

# Compare results across all runs
uv run ctx-rm compare ./results
```

### Run All Benchmarks

```bash
# All 16 tasks × 3 modes
uv run ctx-rm bench --all

# With a specific policy
uv run ctx-rm bench --all --policy arc

# Compare everything
uv run ctx-rm compare ./results
```

---

## CLI Reference

### `ctx-rm info`

Displays system status: version, available drivers, policies, scorers, embedding providers, store configuration, loaded tasks, and token budget.

### `ctx-rm tasks`

Lists all 16 benchmark tasks with their ID, title, eviction pressure type, turn count, needle count, and evaluation check count.

### `ctx-rm bench`

Runs benchmark experiments. Supports single-task or batch-all modes.

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--task` | `CR-001` through `SPEC-001` | `CR-001` | Task ID to run |
| `--mode` | `minimal`, `ctx-rm`, `full` | `ctx-rm` | Session mode |
| `--policy` | `lru`, `clock`, `budget`, `arc`, `innodb` | `budget` | Eviction policy (ctx-rm mode only) |
| `--scorer` | `heuristic`, `ollama`, `sequential` | `heuristic` | Scoring strategy |
| `--budget` | integer | `100000` | Token budget for active context |
| `--batch-mode` | `fixed`, `adaptive` | `fixed` | Eviction batch mode |
| `--max-turns` | integer | `30` | Max agent turns |
| `--enable-recall` | flag | — | Enable page-fault recall from warm/cold |
| `--live` | flag | — | Show live TUI dashboard during run |
| `--output` | path | `results` | Output directory |
| `--all` | flag | — | Run all tasks × 3 modes |

**Output structure:**
```
results/
├── CR-001/
│   ├── minimal/
│   │   └── llamacpp/
│   │       └── run-1/
│   │           ├── metrics.json        # Token usage, eviction stats
│   │           └── evaluation.json     # Pass/fail for each check
│   ├── ctx-rm/
│   │   └── llamacpp/
│   │       └── budget/
│   │           └── run-1/
│   │               └── ...
│   └── full/
│       └── llamacpp/
│           └── run-1/
│               └── ...
```

### `ctx-rm experiment`

Runs multi-combination experiments from a YAML config. Sweeps across tasks, modes, policies, budget levels, and multiple runs.

```bash
# Run a predefined experiment suite
uv run ctx-rm experiment docs/experiments/eviction_accuracy.yaml

# Experiment configs define: tasks, modes, policies, budgets, runs, scorer, recall
```

### `ctx-rm analyze`

Analyzes experiment results and displays evidence tables with per-EVID verdicts.

```bash
uv run ctx-rm analyze results/experiments/
```

### `ctx-rm compare`

Reads all results directories and generates a summary table showing token usage, eviction stats, and task success rate across modes, drivers, and policies.

```bash
uv run ctx-rm compare ./results
```

---

## Configuration

All settings are configurable via environment variables with the `CTX_RM_` prefix, or programmatically via the `CtxRmConfig` Pydantic settings class.

### Core Settings

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `token_budget` | `CTX_RM_TOKEN_BUDGET` | `200000` | Max tokens in active context |
| `headroom_ratio` | `CTX_RM_HEADROOM_RATIO` | `0.15` | Fraction of budget kept free (triggers eviction at 85%) |
| `policy` | `CTX_RM_POLICY` | `budget` | Default eviction policy |
| `scorer` | `CTX_RM_SCORER` | `heuristic` | Scoring strategy (`heuristic` or `ollama`) |

### Scorer Settings

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `recency_halflife` | `CTX_RM_RECENCY_HALFLIFE` | `300.0` | Seconds for recency decay half-life |
| `ollama_host` | `CTX_RM_OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `ollama_model` | `CTX_RM_OLLAMA_MODEL` | `None` (auto) | Preferred Ollama model (None = first available) |
| `ollama_max_concurrent` | `CTX_RM_OLLAMA_MAX_CONCURRENT` | `4` | Max parallel Ollama scoring requests |

### Storage Settings

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `db_path` | `CTX_RM_DB_PATH` | `:memory:` | SQLite path for ColdStore (`:memory:` for in-memory) |
| `warm_max_items` | `CTX_RM_WARM_MAX_ITEMS` | `64` | Max segments in warm cache |
| `warm_max_tokens` | `CTX_RM_WARM_MAX_TOKENS` | `50000` | Max tokens in warm cache |

### Watcher Settings

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `watcher_interval` | `CTX_RM_WATCHER_INTERVAL` | `5.0` | Seconds between eviction checks |
| `watcher_threshold` | `CTX_RM_WATCHER_THRESHOLD` | `0.70` | Context utilization that triggers eviction |

### Example: Custom Configuration

```bash
# Use ARC policy with Ollama scoring, larger budget, persistent store
CTX_RM_POLICY=arc \
CTX_RM_SCORER=ollama \
CTX_RM_TOKEN_BUDGET=500000 \
CTX_RM_DB_PATH=./ctx-rm.db \
uv run ctx-rm bench --task CR-001 --mode ctx-rm
```

---

## Eviction Policies

ctx-rm ships with five eviction policies, all implementing the `EvictionPolicy` ABC. Each policy receives lifecycle hooks (`on_ingest`, `on_access`, `on_evict`) called by the ContextBus as segments move through tiers.

### LRU (Least Recently Used)

The simplest policy. Evicts the segment with the oldest `last_accessed` timestamp first. Good baseline, but blind to frequency and content importance.

```bash
uv run ctx-rm bench --task CR-001 --mode ctx-rm --policy lru
```

### CLOCK (Second Chance)

PostgreSQL-style clock sweep. Each segment gets a reference bit set on access. The clock hand sweeps; segments with the bit set get a second chance (bit cleared), while segments without it are evicted. Approximates LRU with lower overhead.

```bash
uv run ctx-rm bench --task CR-001 --mode ctx-rm --policy clock
```

### BudgetAware (Default)

Composite scoring policy. Delegates to the active Scorer to compute relevance/staleness/redundancy scores, then evicts segments with the lowest composite score. Falls back to LRU ordering when scores are equal. This is the recommended default — it balances recency, frequency, and role importance.

```bash
uv run ctx-rm bench --task CR-001 --mode ctx-rm --policy budget
```

### ARC (Adaptive Replacement Cache)

Based on the [ARC paper](https://www.usenix.org/conference/fast-03/arc-self-tuning-low-overhead-replacement-cache) by Megiddo & Modha. Maintains four lists:

- **T1**: Segments seen once recently (recency list)
- **T2**: Segments seen multiple times recently (frequency list)
- **B1**: Ghost entries for recently evicted T1 segments
- **B2**: Ghost entries for recently evicted T2 segments

An adaptive parameter `p` shifts the balance between recency and frequency based on ghost hits. A B1 hit means recency should be favored (increase p); a B2 hit means frequency should be favored (decrease p). Ghost lists store only `seg_id` and `token_count` — no content, per the original paper.

```bash
uv run ctx-rm bench --task CR-001 --mode ctx-rm --policy arc
```

### InnoDB (Split LRU with Midpoint Insertion)

Inspired by MySQL InnoDB's buffer pool management. Maintains two sublists:

- **New (young)**: Protected sublist for frequently accessed segments
- **Old**: Insertion point for new segments

New segments enter at the **midpoint** (3/8 = 37.5%, matching InnoDB's `innodb_old_blocks_pct=37`). A segment only promotes from old to new on **re-access** — a single access is not enough. This prevents scan pollution: a large file read that touches many segments won't flush the hot working set from the new sublist.

```bash
uv run ctx-rm bench --task CR-001 --mode ctx-rm --policy innodb
```

---

## Benchmark System

The benchmark system evaluates whether intelligent context removal can match full-context quality at lower token cost. It drives real LLM agents through multi-turn coding tasks with needle injection and noise generation, then evaluates the results.

### Three Session Modes

| Mode | Strategy | What it tests |
|------|----------|--------------|
| **Minimal** | Only current turn prompt, no history | Lower bound on quality, upper bound on efficiency |
| **ctx-rm** | Greedy ingest + background removal + recall | The hypothesis: removal matches full-context quality at minimal cost |
| **Full** | Accumulate everything, no management | Upper bound on quality, lower bound on efficiency |

### Task Design

16 benchmark tasks test different eviction pressure patterns:

| Task | Title | Pressure Pattern |
|------|-------|-----------------|
| CR-001 | Legacy Flag Cascade | Gradual buildup |
| CR-002 | Migration Order Sensitivity | Interleaved noise |
| CR-003 | Protocol Handshake Sequence | Sudden injection |
| CR-004 | Log Spam Diagnosis | Gradual buildup |
| CR-005 | Generated Code Noise | Sudden injection |
| CR-006 | Dependency Tree Shock | Sudden injection |
| CR-007 | Alternating API Clients | Interleaved noise |
| CR-008 | Refactor Outdated Comments | Gradual buildup |
| CR-009 | Test Harness Clue | Interleaved noise |
| CR-010 | Multi Issue Thread | Sudden injection |
| MULTI-001 | Cross-file Constraint | Sudden injection |
| TRACE-001 | Bug Hunt in Log Noise | Sudden injection |
| SPEC-001 | Config Synthesis from Spec | Sudden injection |
| SCALE-001 | Multi-department Analytics | High volume (20K tokens) |
| SCALE-002 | Cross-reference Reconciliation | High volume (30K tokens) |
| SCALE-003 | Information Synthesis | High volume (40K tokens) |

Each task contains:
- **Needles**: Critical facts/code injected at specific turns that must be retained
- **Noise**: Synthetic content injected at specific turns to pressure eviction
- **Evaluation checks**: File assertions run against the fixture directory after all turns complete

### Evaluation Assertions

Four assertion types verify agent output against fixture files:

| Assertion | Description |
|-----------|-------------|
| `file_contains` | File must contain a specified string |
| `file_not_contains` | File must not contain a specified string |
| `file_contains_in_order` | Strings must appear in the file in specified order |
| `file_equals` | File must contain a specified substring (must-preserve content) |

### Metrics Captured

Each benchmark run produces:

- **metrics.json**: Per-turn snapshots of active tokens, utilization, warm/cold counts; full eviction log with scores, reasons, and timing; recall events with source tier; ingestion timeline by role/source; agent response token counts per turn
- **evaluation.json**: Pass/fail for each assertion check
- **response_log.jsonl**: Full agent responses for every turn (append-only JSONL)

---

## Project Structure

```
ctx-rm/
├── pyproject.toml                           # Project config, deps, CLI entry point
├── README.md                                # This file
│
├── src/ctx_rm/
│   ├── __init__.py                          # Package root, version
│   ├── config.py                            # CtxRmConfig (Pydantic settings, CTX_RM_ env prefix)
│   │
│   ├── core/                                # Engine internals
│   │   ├── segment.py                       # Segment model (Pydantic), Tier enum, SegmentRole enum
│   │   ├── bus.py                           # ContextBus — central coordinator (ingest/score/evict/recall)
│   │   ├── graveyard.py                     # TieredStore — WarmCache, ColdStore (SQLite), ZombieQueue
│   │   ├── scorer.py                        # Scorer ABC, HeuristicScorer (recency + frequency + role)
│   │   ├── scorer_sequential.py             # SequentialScorer — task-aware conditional scoring
│   │   ├── adaptive.py                      # AdaptiveWeights — feedback-driven scoring adaptation
│   │   ├── feedback.py                      # FeedbackTracker — eviction/recall/eval event log
│   │   ├── tokenizer.py                     # tiktoken cl100k_base with char/4 fallback
│   │   ├── embedding.py                     # EmbeddingProvider ABC, HashingEmbeddingProvider, cosine_similarity_batch
│   │   └── policies/                        # Eviction policy implementations
│   │       ├── base.py                      # EvictionPolicy ABC (select_evictions + lifecycle hooks)
│   │       ├── lru.py                       # LRUPolicy
│   │       ├── clock.py                     # ClockPolicy (PostgreSQL-style second chance)
│   │       ├── budget.py                    # BudgetAwarePolicy (composite score + LRU fallback)
│   │       ├── arc.py                       # ARCPolicy (T1/T2 + B1/B2 ghost lists, adaptive p)
│   │       └── innodb.py                    # InnoDBPolicy (split LRU, midpoint insertion at 3/8)
│   │
│   ├── watch/
│   │   └── watcher.py                       # Async background eviction (interval/threshold/per-turn/hybrid)
│   │
│   ├── agents/                              # Autonomous agent loop
│   │   ├── loop.py                          # AgentLoop — driver + tools + ContextBus + pair integrity
│   │   └── tools.py                         # 6 sandboxed tools (read_file, write_file, list_dir, etc.)
│   │
│   ├── drivers/                             # Agent drivers
│   │   └── llamacpp.py                      # HTTP driver for llama-server (retry, JSON recovery)
│   │
│   ├── benchmarks/                          # Benchmark harness
│   │   ├── models.py                        # BenchmarkSuite, Task, Needle, EvalCheck (Pydantic v2)
│   │   ├── loader.py                        # TaskLoader — YAML → validated BenchmarkSuite
│   │   ├── executor.py                      # TurnExecutor — builds multi-turn sequences with needle/noise
│   │   ├── fixtures.py                      # FixtureManager — copy fixture dirs to temp for isolation
│   │   ├── evaluator.py                     # Evaluator — runs file assertions (4 types)
│   │   └── runner.py                        # BenchmarkRunner (3 modes, AgentLoop-based)
│   │
│   ├── integrations/                        # Optional integrations
│   │   ├── sentence_transformers.py         # SentenceTransformerProvider (optional dep)
│   │   ├── ollama_scorer.py                 # OllamaScorer — LLM scoring via local Ollama
│   │   └── llm_scoring_backend.py           # Pluggable LLM scoring helpers for SequentialScorer
│   │
│   ├── telemetry/
│   │   └── metrics.py                       # MetricsCollector — per-turn snapshots, JSON export
│   │
│   └── cli/
│       ├── main.py                          # Typer CLI — info, tasks, bench, compare commands
│       └── tui.py                           # Live TUI dashboard + post-run Rich summary
│
├── tests/                                   # 171 tests across 6 files
│   ├── core/                                # Bus, graveyard, sequential scorer
│   ├── agents/                              # AgentLoop, recall, pair integrity
│   ├── integration/                         # End-to-end pipeline tests (17 tests)
│   ├── test_harness.py                      # Consolidated harness (YAML-configurable)
│   └── configs/                             # YAML test configurations
│
├── benchmarks/
│   └── fixtures/                            # 16 mini-repo fixtures (one per task)
│       ├── legacy_flag_cascade/
│       ├── migration_order_sensitivity/
│       ├── protocol_handshake_sequence/
│       ├── log_spam_diagnosis/
│       ├── generated_code_noise/
│       ├── dependency_tree_shock/
│       ├── alternating_api_clients/
│       ├── refactor_outdated_comments/
│       ├── test_harness_clue/
│       └── multi_issue_thread/
│
└── docs/
    ├── architecture.md                      # System design document
    ├── tiered_graveyard.md                  # Theoretical foundation (OS/DB → LLM mapping)
    ├── competitive_analysis.md              # MemAct, SWE-Pruner, ACON comparison
    ├── landscape.md                         # Research bibliography
    ├── context_removal_benchmark_tasks.yaml # 16 task definitions (YAML)
    └── experiments/                         # YAML experiment configs
        ├── eviction_accuracy.yaml           # BudgetAware vs LRU across SCALE tasks
        ├── recall_effectiveness_on.yaml     # Recall on vs off
        ├── recall_effectiveness_off.yaml    # Recall disabled baseline
        ├── budget_sensitivity.yaml          # Budget sweep (1K-100K tokens)
        ├── noise_degradation.yaml           # ctx-rm vs full across diverse tasks
        └── context_window_scaling.yaml      # Quality at increasing budget levels
```

---

## Extending ctx-rm

### Adding a New Eviction Policy

1. Create `src/ctx_rm/core/policies/my_policy.py`:

```python
from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.segment import Segment


class MyPolicy(EvictionPolicy):
    @property
    def name(self) -> str:
        return "my_policy"

    def select_evictions(
        self, candidates: list[Segment], tokens_to_free: int
    ) -> list[Segment]:
        # Your eviction logic here
        ranked = sorted(candidates, key=lambda s: your_score(s))
        return self._fill_to_budget(ranked, tokens_to_free)

    # Optional lifecycle hooks — called by ContextBus
    def on_ingest(self, seg: Segment) -> None:
        # Track new segment arrival
        pass

    def on_access(self, seg: Segment) -> None:
        # Track recall/access event
        pass

    def on_evict(self, seg: Segment) -> None:
        # Clean up internal state for evicted segment
        pass
```

2. Export it in `src/ctx_rm/core/policies/__init__.py`
3. Register it in `_create_policy()` in `src/ctx_rm/benchmarks/runner.py`
4. Add it to the `PolicyName` StrEnum in `src/ctx_rm/cli/main.py`

### Adding a New Scorer

1. Implement the `Scorer` ABC:

```python
from ctx_rm.core.scorer import Scorer
from ctx_rm.core.segment import Segment


class MyScorer(Scorer):
    def score_batch(
        self, candidates: list[Segment], context: list[Segment]
    ) -> None:
        for seg in candidates:
            # Set these four fields on each segment:
            seg.relevance_score = ...   # [0, 1]
            seg.staleness_score = ...   # [0, 1]
            seg.redundancy_score = ...  # [0, 1]
            seg.composite_score = ...   # [0, 1] (weighted combination)
```

2. Register it in `_create_scorer()` in `src/ctx_rm/benchmarks/runner.py`
3. Add it to the `ScorerName` StrEnum in `src/ctx_rm/cli/main.py`

### Adding a New Embedding Provider

1. Implement the `EmbeddingProvider` ABC:

```python
import numpy as np
from ctx_rm.core.embedding import EmbeddingProvider


class MyEmbeddingProvider(EmbeddingProvider):
    @property
    def name(self) -> str:
        return "my_embeddings"

    @property
    def dimensions(self) -> int:
        return 768  # Your embedding dimension

    def embed(self, text: str) -> np.ndarray:
        # Return L2-normalized float32 vector
        vec = your_embed_function(text)
        norm = np.linalg.norm(vec)
        return (vec / norm).astype(np.float32) if norm > 0 else vec

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.stack([self.embed(t) for t in texts])
```

ColdStore uses `cosine_similarity_batch()` (dot product on L2-normalized vectors) for search — ensure your provider returns normalized vectors.

### Running Tests

```bash
# All tests
uv run pytest

# Specific subsystem
uv run pytest tests/core/test_bus.py -v

# With coverage
uv run pytest --cov=ctx_rm --cov-report=term-missing
```

---

## Results

Benchmark results using Nemotron-3-Nano-30B (30B params, Q4) via llama-server:

### SCALE-003: Information Synthesis (40K tokens of context)

The agent must read 10 department reports and produce an executive summary with specific metrics. 40K+ tokens of source material injected into context.

| | **ctx-rm** | **full** |
|---|---|---|
| Result | **PASS (10/10)** | **FAIL (0/10)** |
| Turns | 11 | 30 (hit limit) |
| Prompt tokens | **174,210** | **1,120,656** |
| Evictions | 12 | 0 |
| Recalls | 6 | 0 |
| Budget | 17,677 | 1,000,000 (unlimited) |

Full mode **failed** — the model got stuck in a loop, re-reading the same file for 20+ turns, drowning in 42K tokens of accumulated context per prompt. ctx-rm **passed** by evicting stale noise, recalling data on demand, and keeping each prompt under 20K tokens.

### Per-turn context evolution (ctx-rm)

Metrics instrumentation captures the full lifecycle per turn:

| Turn | Active tokens | Utilization | Tool | What happened |
|------|-------------|-------------|------|------|
| 1 | 13,883 | 79% | run_shell | Listed dirs. 2 noise segments evicted at ingest |
| 4 | 18,314 | 104% | file_read | Read finance report (5K tok). Recall triggered. Eviction fired |
| 7 | 18,123 | 103% | file_write | Wrote summary. 5 evictions — biggest cleanup |
| 8 | 8,798 | 50% | list_dir | Stale read context cleaned. Recall for verification |
| 11 | 9,216 | 52% | done | Task complete. 50% recall rate (6/12) |

### SPEC-001: Config Synthesis

| Task | Mode | Result | Prompt Tokens | Turns | Evictions |
|------|------|--------|--------------|-------|-----------|
| SPEC-001 | **ctx-rm** | **PASS 2/2** | **7,151** | 6 | 1 |
| SPEC-001 | full | PASS 2/2 | 16,707 | 7 | 0 |

ctx-rm passed with **57% fewer prompt tokens** than full mode.

These results use a small local model (30B Q4). The key finding: ctx-rm doesn't just save tokens — on context-heavy tasks, it **enables success** where full-context mode fails because the model can't navigate the noise.

---

## Research Context

ctx-rm is an experimental research project exploring whether background context removal with full recoverability can match full-context quality at a fraction of the token cost.

### Key Hypothesis

> An LLM coding agent that ingests context freely while a background removal engine manages the active window will achieve comparable task success to a full-context agent, at significantly lower token cost — and will outperform both on tasks where noise degrades performance.

### Theoretical Foundation

The eviction policies are direct adaptations of algorithms proven in operating systems and databases:

| Algorithm | Origin | ctx-rm Adaptation |
|-----------|--------|-------------------|
| LRU | Every OS page replacement since 1960s | LRUPolicy |
| CLOCK | BSD Unix, PostgreSQL buffer manager | ClockPolicy (second chance with reference bit) |
| ARC | IBM Almaden, FAST '03 | ARCPolicy (T1/T2 + B1/B2 ghost lists) |
| InnoDB Buffer Pool | MySQL/MariaDB | InnoDBPolicy (split LRU with midpoint insertion) |
| Page Fault | OS virtual memory | Zombie tier → recall to Active |

### Positioning

```
                Context Management Approaches
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │  Curation    │  │  Compaction   │  │   Removal    │
  │  (gatekeep)  │  │  (summarize)  │  │  (evict)     │
  └──────────────┘  └──────────────┘  └──────────────┘
  LLMLingua,         Claude Code's     ctx-rm
  Selective Context,  auto-compact,     (this project)
  LangChain CE       ACON, CSIM
```

### Closest Prior Art

| Project | Relationship to ctx-rm |
|---------|----------------------|
| [MemAct](https://github.com/YuxiangZhang0114/MemAct) | Treats memory as learnable action (RL). ctx-rm is background + agent-agnostic |
| [SWE-Pruner](https://github.com/Ayanami1314/swe-pruner) | Code-specific pruning (inline). ctx-rm is async + multi-content-type |
| [ACON](https://github.com/microsoft/acon) | Compression guideline optimization. ctx-rm evicts (recoverable) vs compresses (lossy) |
| Claude Code compact | 3-tier summarization. ctx-rm preserves originals in graveyard |

### Bibliography

See [docs/landscape.md](docs/landscape.md) for the full bibliography including LLMLingua (EMNLP'23, ACL'24), MemGPT/Letta, Mem0, Zep, SWE-Pruner, MemAct, ACON, and LongBench evaluation benchmarks.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Own agent, not CLI wrapper** | AgentLoop drives llama-server via HTTP. Full control over every message and tool call |
| **Background, not inline** | The Watcher runs as an async task. The agent is never interrupted or aware of eviction |
| **Removal, not compression** | Segments are evicted whole (recoverable), not summarized (lossy). The Graveyard preserves exact content |
| **Separation of concerns** | Scorer/Evictor is a separate process from the task agent — two different "brains" |
| **Pluggable everything** | Policies, scorers, embedding providers, and drivers all implement ABCs — swap freely |
| **SQLite for persistence** | Zero external dependencies. Embedded, sufficient for research workloads |
| **Ollama for LLM scoring** | Local, dynamic model discovery, no API costs. Auto-discovers whatever model you have running |
| **Feature hashing for embeddings** | Zero ML dependency default (numpy + hashlib). Optional upgrade to sentence-transformers |

---

## License

Apache-2.0 — see [LICENSE](LICENSE).
