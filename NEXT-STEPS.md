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

Then run `/gsd:map-codebase` first — ctx-rm has a working codebase with
40+ Python source files, 273 passing tests, full docs, and a CLI. The codebase
mapper will understand the architecture before planning begins.

After mapping, run `/gsd:new-milestone`. Feed it this document as context.

---

## What Exists (v0.2.0 — Engine Complete)

> Sessions 1-6 on branch `iter/01-token-accounting` built the full engine.
> 273 tests (247 unit + 26 integration), all green.

### Core Engine (`src/ctx_rm/core/`)
- **`segment.py`** — Pydantic `Segment` model with 5-tier state (Active/Warm/Cold/Graveyard/Zombie), access tracking (recency, frequency, ref bit), eviction audit trail
- **`bus.py`** — `ContextBus` central coordinator: ingest, score, evict, recall, render context, token budget enforcement with configurable headroom. `search_evicted()` wraps TieredStore.search_all()
- **`graveyard.py`** — Full tiered store: `WarmCache` (in-memory LRU), `ColdStore` (SQLite with keyword search + embedding search + audit log), `ZombieQueue` (page-fault staging), `TieredStore` (orchestrator for all tier transitions). `search_all()` does word overlap for warm + embedding/keyword for cold
- **`scorer.py`** — `HeuristicScorer` (exponential recency decay, log-scaled frequency, role weighting, **source_weight=0.3**). Pluggable `Scorer` ABC.
- **`embedding.py`** — `EmbeddingProvider` ABC, `HashingEmbeddingProvider` (feature hashing, zero ML deps), `cosine_similarity_batch()`. Optional `SentenceTransformerProvider`.
- **`tokenizer.py`** — tiktoken cl100k_base with char/4 fallback
- **`policies/`** — Five eviction policies:
  - `LRUPolicy` — Least Recently Used
  - `ClockPolicy` — PostgreSQL-style second chance
  - `BudgetAwarePolicy` — Composite score + LRU fallback (recommended default)
  - `ARCPolicy` — T1/T2 + B1/B2 ghost lists, adaptive p parameter
  - `InnoDBPolicy` — Split LRU with midpoint insertion at 3/8

### Agent Loop (`src/ctx_rm/agents/`)
- **`loop.py`** — `AgentLoop`: driver + tools + ContextBus + Watcher integration
  - `_render_messages()` sorts system messages first
  - `_try_recall()` searches warm+cold, recalls needle/context sources only
  - Anti-thrashing via `_recalled_ids` set
  - `enable_recall=False` by default, `recalls_made` tracked in `AgentResult`
- **`tools.py`** — 6 sandboxed tools for the agent

### Background Watcher (`src/ctx_rm/watch/`)
- **`watcher.py`** — Async background eviction loop with 4 trigger modes (interval, threshold, per-turn, hybrid)

### Drivers (`src/ctx_rm/drivers/`)
- **`gemini.py`** — Drives `gemini -p --output-format json --yolo` via subprocess
- **`claude.py`** — Drives `claude -p --output-format json --dangerously-skip-permissions` via subprocess
- **`llamacpp.py`** — HTTP driver for llama-server `/v1/chat/completions`
- All parse JSON responses for text, token usage, tool calls, timing

### Benchmark Runner (`src/ctx_rm/benchmarks/`)
- **`runner.py`** — `AgentLoopRunner` orchestrates 3 modes (Minimal, ctx-rm, Full) + `enable_recall` flag
- **`loader.py`** — YAML task loader → validated `BenchmarkSuite`
- **`executor.py`** — Turn-by-turn executor with needle/noise injection
- **`evaluator.py`** — 4 assertion types: `file_contains`, `file_not_contains`, `file_contains_in_order`, `file_equals`
- **`fixtures.py`** — Fixture directory copy + isolation + cleanup
- **`models.py`** — Pydantic v2 models for tasks, needles, eval checks

### Integrations (`src/ctx_rm/integrations/`)
- **`ollama_scorer.py`** — `OllamaScorer`: LLM scoring via local Ollama (15 mocked tests)
- **`sentence_transformers.py`** — Optional embedding provider

### CLI (`src/ctx_rm/cli/`)
- `ctx-rm info` — Shows drivers + components
- `ctx-rm tasks` — Lists all 10 benchmark tasks
- `ctx-rm bench` — Run benchmarks (single task or `--all` batch mode)
- `ctx-rm compare` — Compare results across modes/drivers/policies
- Supports `--driver llamacpp`, `--policy` (all 5), `--scorer` (heuristic/ollama)

### Telemetry (`src/ctx_rm/telemetry/`)
- **`metrics.py`** — Records ingestion/eviction/recall events + per-turn snapshots. JSON export.

### Docs (`docs/`)
- `architecture.md` — System design with CLI-first driver architecture
- `tiered_graveyard.md` — OS/DB theoretical foundation (LRU/LFU/CLOCK/ARC/2Q → LLM context)
- `competitive_analysis.md` — Deep analysis of MemAct, SWE-Pruner, ACON
- `landscape.md` — Research bibliography (LLMLingua, MemGPT, Mem0, Zep, LongBench)
- `context_removal_benchmark_tasks.yaml` — 10 structured benchmark tasks with needle injection

### Tests
- 273 tests (247 unit + 26 integration), all passing
- Coverage: segment model, ContextBus, all 5 policies, WarmCache, ColdStore, ZombieQueue, TieredStore, embeddings, tokenizer, agent loop, recall path, runner, evaluator, fixtures, CLI

### Key Results (Session 6)

| Config | Evictions | Recalls | Needle | Eval |
|--------|-----------|---------|--------|------|
| LRU (no recall) | 2 | 0 | DEAD | FAIL |
| LRU + recall | 1 | 1 | ALIVE | PASS |
| BudgetAware (no recall) | 1 | 0 | ALIVE | PASS |

Recall path proven: evicted needles can be restored to active context via page-fault semantics.

---

## Milestone 1 Remaining Work: "Benchmark Validation"

> Most of Milestone 1 was completed in sessions 1-6. These items remain.

### Phase 7: Task Redesign + Adaptation for Agent Loop

**Goal:** Current benchmark tasks (CR-001 through CR-010) were designed for CLI
agents (gemini/claude subprocess). Adapt them for the custom AgentLoop +
llamacpp driver path. Also design new tasks with realistic noise that exercises
the agent's multi-tool capabilities.

**What to do:**
- Validate all 10 existing tasks work with the AgentLoop runner (currently only EVICT-001 and INTEG-001 validated)
- Replace lorem-ipsum noise with realistic content (large file_read outputs, verbose tool results, irrelevant code context)
- Design 3+ new tasks where context management changes the outcome:
  - **MULTI-001 (Cross-file constraint)**: Needle specifies port 8443 + import constraint. Noise: 2000 tokens of unrelated Python docstrings. Eval: config.yaml contains 8443 AND app.py references config.
  - **TRACE-001 (Bug hunt in log noise)**: Needle is "Root cause: KeyError on 'user_id' in auth.py line 42". Noise: 3000 tokens of verbose log output with red herrings. Eval: fix.py contains specific KeyError handling.
  - **SPEC-001 (Config synthesis from spec)**: Needle is "Must proxy /api to localhost:3000 with SSL termination". Noise: 2000 tokens of existing nginx configs for other services. Eval: nginx.conf contains proxy_pass to localhost:3000.
- Wire `--enable-recall` into CLI flags for bench command
- Run all tasks × 3 modes × llamacpp and capture baseline results
- Parametrized test covering all tasks × configs (budget, lru, lru+recall)

**Success criteria:**
- All tasks produce metrics.json + evaluation.json with llamacpp
- At least 3 tasks show ctx-rm matching or beating full-context
- At least 1 task where minimal fails but ctx-rm passes (noise matters)
- `ctx-rm compare` generates a valid comparison table

---

### Phase 8: Agent Hardening

**Goal:** Make the agent loop production-resilient for long benchmark runs.

**What to build:**
- Retry logic for HTTP 503, timeout, connection reset from llama-server
- Graceful handling of malformed tool call JSON from the LLM
- Max context window tracking (`n_ctx` from `/v1/models` endpoint)
- Error recovery: tool failure → agent can retry or skip
- Wire all retry/error config into `CtxRmConfig`

**Success criteria:**
- Agent handles all common error cases without crashing
- 20-turn sessions complete reliably even with transient llama-server issues

---

### Phase 9: CI & Coverage

**Goal:** GitHub Actions CI, coverage reporting, pre-commit.

**What to build:**
- `.github/workflows/ci.yml` — Run tests + ruff on push/PR
- `pytest-cov` configuration, target 90%+
- Pre-commit hooks (ruff, type checking)

---

## Milestone 2: "Sequential Scoring" (NEW)

> **Inspired by**: "Sequential Attention for Feature Selection" (Yasuda et al., ICLR 2023)
> — `docs/arXiv-2209.14881v3.tar.gz`
>
> **Core insight from the paper**: Feature importance is CONDITIONAL — a feature's
> marginal value depends on what's already selected. Selecting one-at-a-time
> (sequentially) with re-scoring beats one-shot selection. This is provably
> equivalent to Orthogonal Matching Pursuit (OMP) for linear regression.
>
> **Adaptation to ctx-rm**: Replace independent segment scoring with conditional
> scoring — evaluate each segment's marginal value relative to the retained set
> AND the current task. Add a learning loop that adapts scoring weights from
> eviction outcomes (page faults, eval failures) across the session.

### Research Claims (Cascading)

Three experiments, one story:

1. **Conditional > Independent**: SequentialScorer (conditioned on retained set + task)
   outperforms HeuristicScorer (independent scoring) on benchmark tasks.
2. **Adaptive > Static**: A policy that adapts parameters from page-fault and eval
   feedback outperforms fixed-parameter policies over multi-turn sessions.
3. **Full Pipeline**: Background context removal with conditional scoring + adaptive
   eviction + recall achieves full-context quality at a fraction of token cost —
   and exceeds it on noisy tasks.

---

### Phase 1: SequentialScorer — Conditional Segment Scoring

**Goal:** New `SequentialScorer` class that evaluates segment importance
conditioned on (1) the current task, (2) the retained set, and (3) session
feedback history.

**What to build:**
- `src/ctx_rm/core/scorer_sequential.py` — `SequentialScorer` implementing the `Scorer` ABC
- **Task-conditioned marginal loss framing**: The scorer LLM evaluates:
  "Given the agent's current task is T, and segments Y,Z are retained,
  what critical information is lost if segment X is removed?"
- Returns `relevance_score`, `staleness_score`, `redundancy_score`, `composite_score`
  — same interface as HeuristicScorer but with conditional logic
- **Configurable scorer LLM**: Default to a cheap model (qwen2.5 via Ollama, or
  Gemini Flash Lite). Option to use the same model as the agent for highest fidelity.
- Score caching keyed by (segment_hash, retained_set_hash, task_hash)

**Key design decisions:**
- The scorer LLM prompt includes: task description, summary of retained segments
  (not full content — token-efficient), and the candidate segment's full content
- Redundancy is measured conditionally: "how much of X's information is already
  covered by the retained set?" — not pairwise similarity
- Falls back to HeuristicScorer on LLM failure

**Paper analog:** This is the attention weight computation in Sequential Attention —
the softmax over unselected features conditioned on the already-selected set.
In the paper, the model jointly optimizes attention weights and task loss. Here,
the scorer LLM approximates the marginal gain signal that greedy forward selection /
OMP would compute exactly (but expensively).

**Tests needed:**
- Conditional scoring returns different scores for same segment with different retained sets
- Task conditioning changes scores (same segment, same retained set, different task)
- Score cache hit/miss behavior
- Fallback to HeuristicScorer on LLM failure
- A/B test harness: run same task with HeuristicScorer vs SequentialScorer

---

### Phase 2: Adaptive Batch Eviction

**Goal:** Replace fixed batch eviction with adaptive batch sizing — one-at-a-time
near budget, batch more aggressively when far over.

**What to build:**
- Update eviction policies to support adaptive batch sizing
- When context utilization is 85-100% of budget: evict one segment, re-score
  remaining, evict next (maximum adaptivity, mirrors paper's k=1 finding)
- When far over budget (e.g., sudden large ingest): batch evict to get within
  range, then switch to one-at-a-time for fine-tuning
- Add `batch_mode` parameter to `select_evictions()`: `"fixed"` (current behavior)
  or `"adaptive"` (new)

**Paper analog:** The paper's adaptivity experiments (Appendix) show that selecting
1 feature at a time yields accuracy 0.963 on MNIST, while selecting 64 at once
drops to 0.932. Quality degrades gradually with batch size, not as a cliff.
The adaptive approach gives us the best of both: precision where it matters,
speed where it doesn't.

**Tests needed:**
- Adaptive mode evicts one-at-a-time near budget threshold
- Adaptive mode batches when far over budget
- Quality comparison: adaptive vs fixed batch on benchmark tasks

---

### Phase 3: Three-Layer Learning Loop

**Goal:** The scorer and policy adapt their parameters from session feedback,
mirroring how the paper's model jointly optimizes attention weights and task loss
during training.

**Three learning layers:**

| Layer | What Adapts | Speed | Feedback Signal |
|-------|------------|-------|-----------------|
| **Source weights** | Per-source-type multipliers (needle, context, tool, assistant, user_task, user_message) | Fast (per-turn) | Page fault source types — if needles keep getting recalled, boost needle weight |
| **Importance cache** | LLM-scored per-segment values | Medium (on feedback events) | Recall events: recalled segment gets score boost. Eval failure: segments with content related to failed check get boost. Anti-thrashing: segments recalled then re-evicted get penalty |
| **Policy parameters** | Balance between recency/frequency/redundancy/role | Slow (phase transitions) | Cumulative session statistics: recall rate, eval pass rate, eviction churn. If recall rate is high → shift toward conservative retention. If context is stale → shift toward aggressive eviction |

**Phase-aware continuous adaptation:**
- No explicit time-based phases. Adaptation is continuous.
- **Event-driven phase transitions** change the adaptation regime:
  - Page fault → shift to more conservative scoring (reduce eviction aggressiveness)
  - Eval check failure → boost scores of segments with related content
  - Period of zero recalls → shift to more aggressive eviction (context is well-managed)
- This mirrors ARC's adaptive p parameter but generalized across all three layers

**Paper analog:** In Sequential Attention, the model weights and attention weights
are jointly optimized by gradient descent. The training loop IS the learning loop.
In ctx-rm, the agent loop (turn-by-turn execution) plays the role of the training
loop, and page faults / eval outcomes play the role of training loss. The three
layers correspond to: attention logits (source weights), model weights
(importance cache), and training schedule (policy parameters).

**What to build:**
- `src/ctx_rm/core/feedback.py` — `FeedbackTracker` that records events:
  - `on_recall(segment)` — page fault happened
  - `on_eval_result(check, passed)` — evaluation outcome
  - `on_eviction(segment)` — segment was evicted
  - `on_re_eviction(segment)` — segment was recalled then evicted again (churn)
- `src/ctx_rm/core/adaptive.py` — `AdaptiveWeights` that maintains the three layers:
  - `source_weights: dict[str, float]` — per-source multipliers, updated per-turn
  - `importance_adjustments: dict[str, float]` — per-segment score adjustments, updated on events
  - `policy_params: dict[str, float]` — recency/frequency/redundancy balance, updated on phase transitions
- Wire `FeedbackTracker` into `ContextBus` (on_evict, on_recall hooks exist)
- Wire `AdaptiveWeights` into `SequentialScorer` (modifies scores before eviction)

**Tests needed:**
- Source weights update on recall events (needle recall → needle weight increases)
- Importance cache updates on eval failure (related segment scores boosted)
- Policy parameters shift on phase transitions (high recall rate → conservative shift)
- Full session simulation: inject feedback events, verify adaptation trajectory
- Regression: adapted weights should improve recall-to-eviction ratio over a session

---

### Phase 4: Experiment Framework & A/B Harness

**Goal:** Run the three cascading experiments to support the research claims.

**What to build:**
- Experiment configs (YAML or Python) for each comparison:
  1. SequentialScorer vs HeuristicScorer (same policy, same tasks)
  2. Adaptive policy vs static policy (same scorer, same tasks)
  3. Full system: ctx-rm-sequential vs ctx-rm-heuristic vs full-context vs minimal
- Metrics to capture per experiment:
  - Token usage (ingested, evicted, recalled, net active)
  - Recall rate (page faults per turn)
  - Eval pass rate (per check, per task)
  - Eviction precision (% of evicted segments that were never recalled)
  - Adaptation trajectory (source weights, policy params over time)
- Results aggregation with confidence intervals across multiple runs
- Comparison tables and charts for the research paper

**Success criteria:**
- Experiment 1: SequentialScorer achieves ≥ equal eval pass rate at ≤ token cost vs HeuristicScorer on ≥ 7/10 tasks
- Experiment 2: Adaptive policy reduces recall rate (fewer page faults) compared to static, without degrading eval pass rate
- Experiment 3: Full ctx-rm-sequential system matches full-context quality on ≥ 8/10 tasks and exceeds it on ≥ 2 noisy tasks

---

## Architecture Decisions (Locked)

- **CLI-first**: Agents driven via `gemini -p`, `claude -p`, or `llamacpp` HTTP. No SDK-based agents.
- **Tiered storage**: Active → Warm → Cold → Graveyard → Zombie
- **Async background eviction**: Watcher runs as `asyncio.create_task()`, never blocks the agent
- **Pluggable everything**: Policies, scorers, embedding providers, drivers all implement ABCs
- **Two brains**: Task agent and scoring brain are separate processes. Scorer LLM defaults to cheap model, configurable to match agent model for highest fidelity.
- **Pydantic v2** for all data models
- **SQLite** for persistence (ColdStore), no external dependencies

## Architecture Decisions (New — Milestone 2)

- **SequentialScorer** is a new class, not a modification of HeuristicScorer. Clean A/B comparison.
- **Scorer LLM is configurable**: `--scorer-model` flag. Default: cheap (qwen2.5/Gemini Flash Lite). Option: same as agent.
- **Three learning layers** (source weights, importance cache, policy params) are independent modules wired via events, not tightly coupled.
- **Adaptive batch eviction** is opt-in via `--batch-mode adaptive`. Fixed batch remains default for backward compatibility.
- **Recall source filter** remains: only recall needle/context/user_task/user_message. Never recall assistant_tool_call or tool (pair integrity).

## Tech Preferences (Locked)

- Python 3.12+, Astral `uv` for package management
- `structlog` for structured logging
- `orjson` for fast JSON serialization
- `typer` + `rich` for CLI
- `pytest` + `pytest-asyncio` for tests
- `ruff` for linting

---

## Key Files to Read

Before planning any phase, read these files for full context:

| File | Why |
|------|-----|
| `README.md` | Project overview, architecture diagram, positioning |
| `src/ctx_rm/core/bus.py` | Central coordinator (ingest/score/evict/recall) |
| `src/ctx_rm/core/scorer.py` | Current HeuristicScorer — the baseline to beat |
| `src/ctx_rm/core/graveyard.py` | Tiered store + search_all() for recall |
| `src/ctx_rm/agents/loop.py` | Agent loop with _try_recall() |
| `src/ctx_rm/benchmarks/runner.py` | AgentLoopRunner — 3 modes + enable_recall |
| `src/ctx_rm/core/policies/budget.py` | BudgetAwarePolicy — uses composite_score |
| `src/ctx_rm/core/policies/arc.py` | ARCPolicy — adaptive p parameter (inspiration for Phase 3) |
| `src/ctx_rm/integrations/ollama_scorer.py` | OllamaScorer — existing LLM scoring path |
| `docs/tiered_graveyard.md` | OS/DB theory → tier design |
| `docs/arXiv-2209.14881v3.tar.gz` | Sequential Attention paper (ICLR 2023) |

---

## Future Milestones (Not Yet Planned)

### Milestone 3: "MCP Server & Agent Integration"
- Expose ctx-rm as an MCP server with tools: `score_context`, `evict_chunk`, `recall_chunk`, `search_graveyard`
- Agent skill file (.md) that teaches agents how to invoke ctx-rm
- Hook-based integration: `BeforeAgent` hook for Gemini CLI, `PostToolUse` hook for Claude Code
- Real-time `stream-json` monitoring

### Milestone 4: "Research Paper"
- Run full benchmark suite: all tasks × modes × drivers × policies × scorers
- Three cascading experiments (conditional > independent, adaptive > static, full system)
- Statistical analysis with confidence intervals
- Generate publication-quality charts
- Write up findings — position against MemAct, SWE-Pruner, ACON, Sequential Attention
- Cite the OS/DB analogy (original contribution) AND the Sequential Attention adaptation (Milestone 2 contribution)

### Milestone 5: "Production Packaging"
- `pip install ctx-rm` distribution
- PyPI publishing
- Docker image for isolated benchmarking
- GitHub Actions for automated benchmark runs
