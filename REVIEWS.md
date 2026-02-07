Technical Review: ctx-rm — Context Removal Engine for LLM Agents
1. Executive Summary
ctx-rm is a well-engineered research prototype that applies OS/DB memory management metaphors to LLM context window management. The core engine (tiered storage, five eviction policies, benchmark harness) is real — not vaporware — with ~40 source files and 200+ tests. The OS/DB analogy is the project's genuine intellectual contribution and is mostly sound, though it gets stretched in places. The Milestone 2 plan (Sequential Scoring) is the weakest part: it over-maps a training-time feature selection paper onto an inference-time problem, proposes an expensive LLM-in-the-loop scorer without adequately addressing latency/cost, and layers three adaptation mechanisms where one would suffice. The benchmark suite is a strength but has methodological blind spots that could undermine the research claims.
2. Strengths
The framing is genu
Click here to configure a worktree setup script. This will be executed on every new worktree and can be used to configure dependencies or environment variables.
Don't show again.
inely novel. Treating context management as a page replacement problem — not compression, not curation — is a clean third option. The evict-whole-and-recall-on-demand design preserves information fidelity in a way summarization cannot. This is the project's real contribution and it deserves a paper on its own.
The implementation is real. The CLOCK policy is a faithful implementation. The ARC policy captures the core ideas (T1/T2/B1/B2 ghost lists, adaptive p). The tiered store (graveyard.py, ~450 lines of logic) with Warm/Cold/Graveyard/Zombie tiers and search_all() is functional. The ContextBus is a clean coordinator. This is not a design doc masquerading as software.
The benchmark design is thoughtful. Three session modes (minimal/ctx-rm/full) create a proper evaluation sandwich. The needle-in-noise pattern with three pressure profiles (gradual, interleaved, sudden) tests meaningfully different eviction scenarios. The four assertion types are appropriate for file-based evaluation.
The architecture is genuinely pluggable. Policies, scorers, embedding providers, and drivers all implement ABCs. Adding a new eviction policy is ~30 lines. This makes experimentation cheap.
The "two brains" separation is correct. Keeping the task-solving agent and the context-scoring engine as separate concerns is an important design decision. It means the system can work with any agent without requiring agent cooperation.
3. Weaknesses
The OS/DB analogy breaks down at recall. In real virtual memory, a page fault is transparent — the process doesn't know it happened. In ctx-rm, recall is not transparent: the agent receives the recalled content as new context, which changes the conversation semantics. The recalled segment arrives at a different position in the context window and lacks the surrounding conversational flow it originally appeared in. This is more like a database SELECT than a page fault, and the distinction matters for evaluating whether the "virtual memory" framing is honest.
The InnoDB policy has a real bug. old_max_tokens is calculated but never enforced. The midpoint insertion that is the entire point of InnoDB-style buffer management is declared but not actually implemented. The README confidently describes "midpoint insertion at 3/8 = 37.5%, matching InnoDB's innodb_old_blocks_pct=37" — but the code doesn't enforce this boundary. This is a claim-vs-reality gap.
The ARC implementation is simplified. The standard ARC algorithm enforces |T1| + |T2| ≤ c and |T1| + |B1| + |T2| + |B2| ≤ 2c. The implementation does not enforce these invariants, relying instead on external eviction calls to manage capacity. The p adaptation formula also differs from the original paper. This is fine for a research prototype but should be acknowledged, not presented as a faithful adaptation.
The test count is inconsistent. The README badge says "128 passing," NEXT-STEPS says "273 tests (247 unit + 26 integration)." The actual count appears to be somewhere around 200+ when parametrized tests expand. This kind of discrepancy — especially in a research project — erodes trust in other claimed numbers.
The benchmark tasks, while structurally sound, test a narrow definition of "context management." All 10 tasks follow the same pattern: inject needle, inject noise, check if the agent preserves the needle in its output. This tests retention, not reasoning. A more challenging test would require the agent to synthesize information from multiple retained segments, or to reason about the absence of information it knows was evicted.
No actual benchmark results are presented. The README describes the benchmark system in detail but never shows results. The only results in NEXT-STEPS are from a single controlled unit test (Session 6: LRU vs BudgetAware, 1-2 evictions). There is no evidence that the system works at scale (20-turn sessions, 100K+ token contexts, real agent interactions).
4. Specific Concerns
Milestone 2: Sequential Scoring
The paper analogy is strained. "Sequential Attention for Feature Selection" (Yasuda et al., ICLR 2023) addresses a training-time optimization problem: given a fixed dataset, learn which features to select by backpropagating through a differentiable attention mask. The key mechanism — gradient-based optimization of attention weights jointly with task loss — has no analog in ctx-rm. There is no gradient, no backpropagation, no differentiable objective. The connection to OMP (Orthogonal Matching Pursuit) is formal: OMP works because the features have a fixed relationship to the target. LLM context segments do not have this structure.
What the plan actually proposes is greedy conditional scoring via an LLM judge — which is a fine idea on its own, but does not need the Sequential Attention paper to justify it. Claiming this is "provably equivalent to OMP" or an "adaptation of Sequential Attention" overstates the connection. It is more accurately described as "conditional importance scoring inspired by the insight that marginal value depends on the retained set."
The SequentialScorer has a cost problem. Evaluating each segment's marginal value requires an LLM call that includes: (1) the task description, (2) a summary of the retained set, and (3) the candidate segment's full content. With N candidate segments, this is O(N) LLM calls per eviction cycle. If the eviction cycle runs every 5 seconds (watcher interval), and there are 50 candidate segments, that's 50 LLM calls every 5 seconds. Even with a "cheap" model like qwen2.5, this is:
Latency: 50 × ~200ms = 10 seconds per cycle (blocking, serialized). Even at 4 concurrent calls, ~2.5 seconds.
Token cost: Each call sends ~500 tokens of task + ~1000 tokens of retained set summary + ~500 tokens of candidate = ~2000 input tokens per call × 50 = 100K tokens per eviction cycle. This is the same order of magnitude as the context budget itself.
The score caching proposal (keyed by segment_hash + retained_set_hash + task_hash) is a partial mitigation, but retained_set_hash changes every time a segment is evicted or recalled, invalidating the entire cache. In practice, cache hit rates will be low during active eviction.
The three-layer learning loop is over-engineered. Source weights, importance cache, and policy parameters — each with different update speeds and feedback signals — create a system with 3 × N interacting parameters. The ARC policy already demonstrates that a single adaptive parameter (p) can effectively balance competing objectives. Adding three adaptation layers before demonstrating that one layer helps is premature complexity. The risk is that the layers interact in unexpected ways (e.g., source weight adaptation fights policy parameter adaptation), making the system hard to debug and hard to attribute improvements to specific mechanisms.
A simpler design: start with source weight adaptation only (fast, per-turn, directly interpretable). Measure whether it helps. Then add the next layer only if there is a demonstrated gap.
The adaptive batch eviction claim is weak. The paper's evidence (MNIST: 0.963 accuracy for k=1 vs 0.932 for k=64) is about feature selection during model training. The analogy to context eviction is: "removing segments one at a time is better than removing them in batches." This is plausible but the evidence is not transferable — MNIST feature importance is a fixed function of the trained model, while segment importance in an LLM context is a dynamic function of the conversation state. The paper's result could just reflect that MNIST has strong feature interactions, which says nothing about LLM context segments.
Benchmark Design
10 tasks × 3 modes × 5 policies = 150 data points is thin for research claims. With no repeated trials and no confidence intervals, any result is anecdotal. The plan mentions "confidence intervals across multiple runs" in Phase 4, but LLM responses are stochastic — you need at minimum 5-10 runs per configuration to get meaningful statistics, which means 750-1500 benchmark executions. At ~20 turns each with real LLM calls, this is expensive.
The evaluation methodology tests retention, not utility. All checks are file assertions: "does the output file contain string X?" This measures whether the agent remembered a fact, not whether it used it correctly in context. A more robust evaluation would include tasks where the agent must integrate multiple pieces of retained information, or where retaining the wrong information actively degrades performance (not just adds noise).
The benchmarks can be gamed by pattern matching. If the needle is "SAFE_MODE must remain true when LEGACY_AUTH is enabled" and the evaluation checks for SAFE_MODE = true in a config file, an agent that simply pattern-matches on keywords could pass without understanding the constraint. The noise content would need to include contradictory information (e.g., "SAFE_MODE should be false for performance") to test whether the agent distinguishes signal from noise, not just signal from absence.
5. Suggestions
In order of importance:
Fix the InnoDB policy before claiming it. Either implement the midpoint enforcement or remove InnoDB from the policy list and README. Claiming a feature that doesn't work is worse than not having the feature.
Run and publish actual benchmark results for Milestone 1. The system exists. Run all 10 tasks × 3 modes × 2-3 policies with at least 3 repetitions each. Publish the raw numbers. This is the single most important thing the project can do to establish credibility. Everything else (Sequential Scoring, adaptive learning, paper) depends on having a baseline that shows context removal actually works.
Decouple the SequentialScorer from the Sequential Attention paper. The idea of conditional scoring — evaluating a segment's marginal value given the retained set — is good and doesn't need a strained analogy to feature selection. Frame it as "conditional importance scoring" inspired by the greedy forward selection literature broadly (OMP, submodular maximization, etc.), not as an "adaptation" of a specific paper. This makes the contribution clearer and the claims more defensible.
Start the three-layer learning loop as one layer. Implement source weight adaptation only. Measure its effect. Add complexity only when you have evidence the simpler approach is insufficient. This follows the project's own principle of pluggability — each layer should be independently evaluable.
Add adversarial benchmark tasks. Design 2-3 tasks where noise contains contradictory information that actively misleads the agent. This tests whether eviction policies actually improve reasoning quality, not just memory. Example: needle says "use port 8443," noise says "the standard port is 8080, always use 8080 for this service." If the agent outputs 8080 in full-context mode but 8443 in ctx-rm mode, that is a compelling result.
Address the recall semantics honestly. A recalled segment arrives in a different position without its original conversational context. Acknowledge this as a fundamental difference from OS page faults and measure its impact. A recalled segment might confuse the agent more than help it. The Session 6 result (LRU + recall: needle ALIVE, PASS) is one data point — does recall help on tasks where the needle requires integration with surrounding context?
Budget the SequentialScorer's cost explicitly. Before building it, compute the expected token cost per eviction cycle for 20, 50, and 100 candidate segments. Set a cost ceiling (e.g., "the scorer must use < 5% of the context budget in tokens per session"). Design the scorer to meet this ceiling, not the other way around.
Acknowledge the ARC simplification. Add a note in the docs or code that the ARC implementation omits capacity invariants and uses a modified p adaptation formula. Researchers reading the code will notice; better to own it.
6. Questions for the Authors
What are the actual benchmark results? The system has been built through 6 sessions. Have you run the full benchmark suite against a real LLM agent? If so, what were the results? If not, why not — and doesn't this undermine the entire project narrative?
How does recall affect agent behavior in practice? When a segment is recalled from the graveyard and injected back into context, does the agent treat it as new information or does it recognize it? Does the position of the recalled segment matter? Have you observed cases where recall hurts performance?
What is the actual token cost of a 20-turn session in each mode? The README claims ctx-rm achieves "comparable task success at significantly lower token cost" but provides no numbers. What is the actual token savings? 10%? 50%? 90%?
Why five eviction policies instead of one good one? Having five policies is a strength for research exploration but a liability for making claims. If BudgetAware is the recommended default, why are LRU, CLOCK, ARC, and InnoDB in the critical path? Is the plan to show that the choice of policy matters (comparative study) or that one policy dominates?
How does the system handle the cold-start problem? In the first few turns of a session, there is no access history, no frequency data, and no feedback signal. All policies degenerate to FIFO or random. Is this addressed?
For the SequentialScorer: what happens when the scorer LLM disagrees with the task agent? The scorer is a "second brain" evaluating segment importance. But it's a different (cheaper) model with a different understanding of the task. If the scorer thinks a segment is unimportant but the task agent would have used it, the eviction is a mistake that no amount of recall can fully fix (because the agent doesn't know what it doesn't know). How do you detect and mitigate this?
Is the MCP server milestone (Milestone 3) actually needed before the paper (Milestone 4)? The paper could be written with the current CLI-based benchmark system. Building an MCP server is an engineering project that does not advance the research claims. Consider reordering.
What is the target venue for the paper? The answer significantly affects what experiments are needed. A systems venue (OSDI/SOSP) would want throughput numbers and scalability. An NLP venue (EMNLP/ACL) would want comparison to LLMLingua and MemGPT on standard benchmarks like LongBench. A ML venue (ICLR/NeurIPS) would want the Sequential Attention connection to be formally justified. The plan doesn't specify, which makes it hard to evaluate whether the proposed experiments are sufficient.

---


Review: ctx-rm — Context Removal Engine for LLM Agents
1. Executive Summary
ctx-rm is a technically impressive and intellectually coherent research project. The core insight—applying OS virtual memory and database buffer pool algorithms (ARC, CLOCK, InnoDB) to LLM context management—is genuinely novel and provides a strong theoretical foundation. The proposed move to "Sequential Scoring" (Milestone 2) is ambitious and theoretically sound, adapting proven ML feature selection concepts to inference-time context management. However, the project faces significant risks regarding the latency and cost of the proposed conditional scoring mechanisms, and the "page fault" analogy, while powerful, glosses over the difficult problem of triggering recalls deterministically.
2. Strengths
Strong Theoretical Foundation: The mapping of OS/DB concepts to LLM context is not just a loose metaphor but is implemented rigorously (e.g., InnoDB's midpoint insertion, ARC's ghost lists). This gives the project a principled way to reason about eviction that ad-hoc heuristics lack.
Clean Architecture: The separation of the "Context Engine" (ContextBus, Scorer, Evictor) from the "Agent Driver" is excellent. It allows ctx-rm to be agent-agnostic and evolve independently of the specific LLM being driven.
Intellectual Honesty in Baselines: The inclusion of "Minimal" (lower bound) and "Full" (upper bound) modes in the benchmark suite is scientifically rigorous. It establishes clear success criteria: matching "Full" quality at "Minimal" cost.
Test Coverage: Having ~273 tests for a research prototype is commendable and suggests a high level of engineering maturity.
3. Weaknesses
The "Page Fault" Illusion: In an OS, a page fault is deterministic—the CPU tries to access an address that isn't mapped, triggering a hardware trap. In ctx-rm, "recall" appears to be a probabilistic search (RAG) running in the background. Calling this a "page fault" masks the hardest problem: how does the system know what it is missing? If the agent doesn't know a segment exists, it won't generate a query to "fault" it in.
Latency & Cost Blind Spot: The Milestone 2 plan for "Sequential Scoring" (asking an LLM to evaluate marginal value) and a "Three-Layer Learning Loop" ignores the runtime cost. Running an LLM-based scorer on every eviction cycle could easily double the latency and cost of the entire system, potentially negating the benefits of context reduction.
Benchmark Scale: While the design of the benchmarks is sound, 10 tasks is a very small sample size given the high variance of LLM outputs. It may be difficult to distinguish signal from noise.
4. Specific Concerns
Technical Soundness: The Recall Mechanism
The README states: Active ← Zombie ← Cold/Graveyard (recall = page fault).
In NEXT-STEPS.md, it mentions: _try_recall() searches warm+cold.
Concern: This implies that "recall" is just a background vector/keyword search running every turn. This is RAG, not Virtual Memory. True virtual memory requires the consumer (the CPU/Agent) to halt and request missing data. If ctx-rm relies on background search, it suffers from the standard RAG failure mode: if the query (current context) doesn't semantically match the missing needle, the "page fault" never happens.
Milestone 2: Sequential Scoring Viability
The plan proposes: "The scorer LLM evaluates: 'Given... segments Y,Z are retained, what critical information is lost if segment X is removed?'"
Concern: This is an $O(N)$ or $O(N^2)$ operation depending on implementation. Even with a "cheap" model (Gemini Flash Lite), doing this for every candidate segment during an eviction cycle is likely too slow for interactive use. The plan mentions caching, but context changes every turn, potentially invalidating the "conditional" part of the score.
Complexity of the "Three-Layer Learning Loop"
Concern: Implementing adaptive Source Weights, Importance Cache, and Policy Parameters simultaneously is a recipe for unstable feedback loops. If the system starts evicting aggressively because of a "zero recall" period, it might cause a failure that leads to a "panic recall," swinging the weights wildly.
5. Suggestions
Profile "Scorer" Overhead Immediately: Before building the full Sequential Scorer, run a simple experiment to measure the latency of LLM-based scoring in the loop. If it adds >2 seconds per turn, the design needs to change (e.g., async scoring that lags behind ingestion).
Redefine "Page Fault" Triggers: Move beyond background search. Explore explicit page faults: allow the Agent to emit a special tool call or token (e.g., <recall query="..."/>) when it feels it is missing context. This aligns better with the "Virtual Memory" analogy (the CPU explicitly requesting data).
Simplify Milestone 2: Cut the "Three-Layer Learning Loop" from the initial scope. Focus solely on Conditional Scoring first. Prove that P(Keep X | Y, Z) is better than P(Keep X). Add the adaptive control loops only after the core signal is validated.
Harden the Benchmark Against Gaming: Ensure the "Realistic Noise" in Phase 7 includes "adversarial noise"—content that looks highly relevant (high semantic similarity) but is actually stale or incorrect. This tests the Scorer's ability to discern value from similarity.
6. Questions for the Authors
Trigger Mechanism: What specifically triggers a _try_recall()? Is it run automatically every turn (polling), or is there a heuristic that detects "missing information"?
Cost Model: Have you calculated the "token return on investment"? i.e., If the Sequential Scorer spends 1,000 tokens to decide which 500 tokens to evict, is the system actually saving resources?
Synchronization: If the Scorer is slow (LLM-based) and Ingestion is fast (pasting a large file), how does the ContextBus handle the backlog? Does it block ingestion (slowing the user) or allow temporary budget overflow?

---

[2 tools called]

Findings first (ordered by severity), then questions and the requested sections.

### Specific Concerns (Ordered by Severity)
- **Critical — Recoverability/virtual memory claims are overstated.** The docs frame ctx‑rm as “virtual memory” with “page‑in/page‑out” and “full recoverability,” but the described recall path is best‑effort search plus staging, not deterministic OS‑style page faults. This is an intellectual honesty gap and weakens the analogy.  
```31:42:README.md
LLM coding agents like [Gemini CLI](https://github.com/google-gemini/gemini-cli) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) operate within a context window — 1M tokens for Gemini, 200K for Claude. In long multi-turn sessions, context fills up. The industry has two responses:

| Approach | How it works | Limitation |
|----------|-------------|------------|
| **Context Curation** | Carefully gate what enters context | Requires upfront decisions about relevance — hard for open-ended tasks |
| **Context Compaction** | Summarize/compress to fit a budget | Lossy — summaries drop details that matter later |

**ctx-rm** explores a third path: **Context Removal**.

> Ingest anything. A background engine scores, evicts, and stores content from the active context. Evicted content is preserved whole and can be recalled on demand. Think of it as **virtual memory for LLM context** — page-in/page-out semantics with full recoverability.

The key insight: OS virtual memory and database buffer pools have solved this problem for decades. A page fault in Linux retrieves the exact page — no information loss. ctx-rm applies the same principle to LLM context.
```
```59:75:README.md
Segments flow through five tiers:

```
Ingest → Active → Warm → Cold → Graveyard
                                     ↓
            Active ← Zombie ← Cold/Graveyard   (recall = page fault)
```

### The Eviction Cycle

1. **Ingest**: New content enters Active. The ContextBus assigns a turn number, checks admission control (large tool outputs may bypass Active and go directly to Warm), and notifies the eviction policy via `on_ingest()`.

2. **Score**: The Scorer evaluates each segment's value. The HeuristicScorer combines three signals — recency (exponential decay), frequency (log-scaled access count), and role weight (system > user > assistant > tool). The optional OllamaScorer calls a local LLM for semantic relevance scoring.

3. **Evict**: When the active context exceeds the token budget (minus a configurable headroom), the eviction policy selects segments to remove. The evicted segment moves to Warm (in-memory LRU cache), then to Cold (SQLite with optional embedding vectors), then to Graveyard (append-only archive).

4. **Recall**: When the agent needs evicted content, a search against Cold/Graveyard returns matching segments. They enter as Zombies (staging tier for validation), then promote back to Active. This is a page fault.
```

- **High — Evidence gap for the core hypothesis.** README asserts parity with full‑context quality at lower cost and superiority on noisy tasks, but the only concrete results shown are a tiny, single‑session table. The claim is far ahead of evidence.  
```648:654:README.md
## Research Context

ctx-rm is an experimental research project exploring whether background context removal with full recoverability can match full-context quality at a fraction of the token cost.

### Key Hypothesis

> An LLM coding agent that ingests context freely while a background removal engine manages the active window will achieve comparable task success to a full-context agent, at significantly lower token cost — and will outperform both on tasks where noise degrades performance.
```
```94:102:NEXT-STEPS.md
### Key Results (Session 6)

| Config | Evictions | Recalls | Needle | Eval |
|--------|-----------|---------|--------|------|
| LRU (no recall) | 2 | 0 | DEAD | FAIL |
| LRU + recall | 1 | 1 | ALIVE | PASS |
| BudgetAware (no recall) | 1 | 0 | ALIVE | PASS |

Recall path proven: evicted needles can be restored to active context via page-fault semantics.
```

- **High — Sequential scoring plan is likely impractical and weakly justified.** Per‑segment conditional LLM scoring plus adaptive batch eviction and a three‑layer learning loop introduce heavy compute, unclear cache reuse, and unstable feedback dynamics. The analogy to training‑time sequential attention doesn’t directly transfer to inference‑time, sparse‑feedback settings, and the plan doesn’t account for scorer cost in comparisons.  
```193:271:NEXT-STEPS.md
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
```
```385:422:README.md
Each of the 10 benchmark tasks (CR-001 through CR-010) is a 20-turn multi-turn coding scenario designed to test different eviction pressure patterns:

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

- **metrics.json**: Total tokens ingested, evicted, recalled; peak and average context utilization; eviction/recall counts; per-turn snapshots
- **evaluation.json**: Pass/fail for each assertion check
- **response_log.jsonl**: Full agent responses for every turn (append-only JSONL)
```

- **High/Medium — Benchmark design risks gaming and weak conclusions.** Ten tasks, single‑seed, string‑based file assertions, and synthetic noise are vulnerable to pattern matching and do not robustly measure context management. The plan’s new tasks still follow the same needle/noise template, so the blind spots persist.  
```385:422:README.md
Each of the 10 benchmark tasks (CR-001 through CR-010) is a 20-turn multi-turn coding scenario designed to test different eviction pressure patterns:
...
Each task contains:
- **Needles**: Critical facts/code injected at specific turns that must be retained
- **Noise**: Synthetic content injected at specific turns to pressure eviction
- **Evaluation checks**: File assertions run against the fixture directory after all turns complete
```

- **Medium — Tiering plus recall filters weaken “full recoverability.”** The system explicitly avoids recalling tool/assistant content, which can easily be the most relevant evidence in coding tasks; this contradicts the “recoverability” framing and could bias benchmarks.  
```351:352:NEXT-STEPS.md
- **Recall source filter** remains: only recall needle/context/user_task/user_message. Never recall assistant_tool_call or tool (pair integrity).
```

- **Low — Documentation consistency issues.** Test counts differ across docs, which undermines trust in the state of the system and the strength of claims.  
```5:8:README.md
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-128%20passing-brightgreen.svg)]()
[![v1.0](https://img.shields.io/badge/version-1.0-orange.svg)]()
```
```25:29:NEXT-STEPS.md
## What Exists (v0.2.0 — Engine Complete)

> Sessions 1-6 on branch `iter/01-token-accounting` built the full engine.
> 273 tests (247 unit + 26 integration), all green.
```

### Questions for the Authors
- How do you **quantify recoverability** today (recall@k, false‑negative rate, time‑to‑recall), and what thresholds would justify “virtual memory” language?
- Will **scorer LLM tokens/latency** be counted in benchmark metrics and comparisons? If not, how will you avoid biased conclusions?
- What is the **expected segment count per task** and the worst‑case scoring load for SequentialScorer? What’s the latency budget?
- How will you **prevent benchmark gaming** (string‑match solutions, needle‑only retention, or memorizing assertion strings)?
- What would **falsify** each of the three milestone‑2 claims in a single, concrete experiment?

### Executive Summary
This is a promising and well‑structured research prototype, but the current claims outpace the evidence and the roadmap introduces heavy complexity before proving the core advantage. The OS/DB analogy is evocative but currently overstated because recall is best‑effort rather than deterministic. The sequential scoring plan is conceptually interesting yet likely impractical without explicit cost accounting and stronger evaluation design. I would treat this as a solid engine and benchmark harness, but not yet as a validated contribution.

### Strengths
- Clear, modular architecture with pluggable policies, scorers, and drivers.
- A concrete, end‑to‑end benchmark harness using real agent CLIs.
- Thoughtful mapping to OS/DB cache policies and eviction patterns.
- Explicit research hypotheses and a staged roadmap with tests and metrics.
- Good focus on recoverable eviction rather than lossy compaction.

### Weaknesses
- Claims of parity with full‑context quality are not yet supported by data.
- Evaluation is narrow (string‑based asserts, synthetic noise, few tasks).
- Milestone‑2 design adds multiple adaptive layers before minimal validation.
- Cost/latency of LLM‑based scoring is missing from metrics and comparisons.

### Suggestions (Ordered by Importance)
- **Define and measure recoverability explicitly** (recall@k, false negatives, time‑to‑recall) and tighten README claims to match measured results.
- **Instrument scorer cost and latency** and include them in benchmark comparisons; run multi‑seed experiments with confidence intervals.
- **Stage Milestone‑2 validation**: start with a minimal SequentialScorer ablation and a simple adaptive batch toggle before the three‑layer learning loop.
- **Strengthen benchmarks** with randomized noise, tool‑output needles, unit/integration tests, and anti‑gaming checks (e.g., require behavioral changes, not strings).
- **Add stronger baselines**: size‑aware caches (TinyLFU/WTinyLFU, GDSF), LRU‑K/2Q, and a retrieval‑only memory baseline; consider a simpler bandit‑style weighting as an alternative to the three‑layer loop.

