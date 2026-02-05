# Competitive Analysis: MemAct, SWE-Pruner, ACON

This section analyzes three recent context-management approaches in detail and positions **ctx-rm** (background context removal) relative to each. Each subsection includes: (a) algorithm/mechanism steps, (b) what worked + limitations, and (c) how **ctx-rm** differs and improves.

Sources:
- MemAct: [arXiv:2510.12635](https://arxiv.org/abs/2510.12635), code: [github.com/ADaM-BJTU/MemAct](https://github.com/ADaM-BJTU/MemAct)
- SWE-Pruner: [arXiv:2601.16746](https://arxiv.org/abs/2601.16746), code: [github.com/Ayanami1314/swe-pruner](https://github.com/Ayanami1314/swe-pruner)
- ACON: [arXiv:2510.00615](https://arxiv.org/abs/2510.00615), code: [github.com/microsoft/acon](https://github.com/microsoft/acon)

---

## MemAct (Memory as Action) — Autonomous Context Curation

### (a) Algorithm / Mechanism (Step-by-Step)
1. **Unify task + memory actions.** The agent’s policy chooses from a joint action space: normal task actions plus memory-editing actions (`Prune&Write`).
2. **Memory action parameterization.** If a memory action is selected, the model outputs:
   - A set of **record IDs** to remove from working memory.
   - A **memory note** that summarizes or reflects the pruned content.
3. **In-place context editing.** The system deletes target records by ID and **appends the memory action record** itself to the context, making the memory note part of the new state.
4. **MDP formalization.** Working memory is a sequence of `(action, observation, id)` records; memory actions are defined as `(target_id_set, memory_content)`.
5. **Training with RL.** The policy is optimized via reinforcement learning on task success, with penalties for exceeding context length constraints.
6. **Dynamic Context Policy Optimization (DCPO).** Because memory edits break monotonic context growth, DCPO **segments trajectories** at memory-edit points into consistent sub-trajectories for stable credit assignment during RL.

### (b) What Worked + Limitations
**Worked:**
- Achieved **~51% average context reduction** while matching or exceeding large-model baselines on long-horizon QA benchmarks.
- Learned **model-specific strategies** (e.g., smaller models prune more aggressively).
- Reduced latency by keeping average context short and avoiding extra summarization passes.

**Limitations (from paper):**
- **Sparse terminal rewards** make credit assignment for memory actions difficult.
- **Lossy compression**: once details are summarized, original information cannot be recovered.
- **No external recovery**: focuses on in-context editing rather than retrieval from persistent stores.
- RL training overhead; some trajectory sampling is inefficient for complex tasks.

### (c) How ctx-rm Differs / Improves
**ctx-rm** targets *background removal across the entire active context*, not just file-read outputs:
- **Broader scope.** SWE-Pruner only prunes read outputs; ctx-rm manages *conversation history, tool outputs, and retrieved docs*.
- **No goal-hint dependency.** ctx-rm does not require explicit “focus” questions to function (though it can use them as signals).
- **Recoverable evictions.** ctx-rm evicts to a memory store so removed lines can be retrieved later; SWE-Pruner discards pruned lines permanently.
- **Pluggable policy.** SWE-Pruner relies on a trained skimmer; ctx-rm can start with lightweight heuristics and later incorporate learned scorers.

Potential synergy: SWE-Pruner can serve as a **front-end reducer** for large file reads, while ctx-rm handles **ongoing eviction** across multi-turn sessions.

---

## ACON (Agent Context Optimization) — Prompt-Optimized Compression

### (a) Algorithm / Mechanism (Step-by-Step)
1. **Define compression targets.**
   - *History compression:* compress interaction history only when it exceeds a threshold.
   - *Observation compression:* compress large observations only when they exceed a threshold.
2. **LLM compressor with guidelines.** A large LLM acts as a compressor guided by a natural-language **compression guideline prompt**.
3. **Contrastive failure collection.** Run tasks with and without compression; keep cases where **full context succeeds but compressed fails**.
4. **Utility-maximization (ut) step.**
   - An optimizer LLM analyzes paired (full vs. compressed) contexts.
   - It generates feedback on what was lost and updates the guideline prompt.
   - Multiple candidate prompts are evaluated; the best is selected.
5. **Compression-maximization (co) step.**
   - Use only successful compressed runs.
   - The optimizer LLM finds redundant information to remove.
   - Update the guideline prompt again to shorten contexts further.
6. **Distillation.** The optimized compressor is distilled into a smaller model to reduce inference overhead.

### (b) What Worked + Limitations
**Worked:**
- **26–54% reduction** in peak tokens across long-horizon agent benchmarks.
- Maintained or improved task performance on some settings.
- Distillation retained **>95%** of the teacher compressor’s accuracy.
- Boosted smaller agent models by reducing context distraction.

**Limitations (from paper):**
- **Compression overhead** can increase cost, especially for history compression (KV-cache disruption).
- Requires **extra LLM calls** for compression and prompt optimization.
- Primarily evaluated on GPT-family models; broader model coverage is unverified.

### (c) How ctx-rm Differs / Improves
**ctx-rm** focuses on *asynchronous eviction and recoverability*, rather than prompt-optimized compression:
- **No prompt-optimization loop.** ctx-rm does not require iterative guideline updates or contrastive failures.
- **Eviction + retrieval vs. summarization.** ctx-rm moves content to a memory store instead of re-summarizing it, allowing recovery of exact details.
- **Lower overhead by design.** ctx-rm can operate with lightweight heuristics and avoid additional LLM calls during compression.
- **Works with any agent loop.** ACON depends on a compressor module and thresholds; ctx-rm wraps any existing loop and uses a background manager.

Potential synergy: ACON’s **optimized compressor** could be used as an *eviction summarizer* inside ctx-rm when space is tight, while ctx-rm provides retrieval and auditability.

**ctx-rm** differs by making removal **asynchronous and externalized** rather than embedded in the agent’s own policy:
- **Background removal vs. policy action.** ctx-rm evicts in the background, avoiding the need for RL-trained memory actions or explicit tool calls inside the agent’s reasoning trace.
- **Recoverability by default.** ctx-rm stores evicted segments in a memory store, enabling **re-injection** later; MemAct’s summarization is lossy and not recoverable.
- **Lower training cost.** ctx-rm does not require end-to-end RL training or DCPO; it can operate with fixed or learned policies externally.
- **Agent-agnostic integration.** ctx-rm can wrap any agent loop (Gemini CLI, local LLMs), while MemAct requires model-level fine-tuning and tool schemas.

Potential synergy: use MemAct’s **Prune&Write** output as a **salience signal** or as a policy for ctx-rm eviction decisions.

---

## SWE-Pruner — Self-Adaptive Context Pruning for Coding Agents

### (a) Algorithm / Mechanism (Step-by-Step)
1. **Goal hint generation.** The agent emits a **natural-language goal** describing what it needs (e.g., “focus on error handling”).
2. **Middleware interception.** SWE-Pruner sits between agent and environment; it intercepts **read operations** (e.g., `cat`, `grep`).
3. **Neural skimmer scoring.**
   - A lightweight reranker model scores token relevance given the goal and full context.
   - Token scores are **aggregated to line-level scores**.
4. **Structured line selection.**
   - A CRF-based pruning head models line retention decisions.
   - Lines above a threshold are retained; others are removed.
5. **Pruned context returned.** The agent receives a **filtered file view** rather than the raw output.
6. **Training data.** Uses a teacher LLM to synthesize goal queries and line-level masks from GitHub code; trains the skimmer on CRF-NLL + rerank losses.

### (b) What Worked + Limitations
**Worked:**
- **23–54% token reduction** on multi-turn coding tasks (SWE-Bench Verified, SWE-QA) with minimal accuracy loss.
- Up to **14.84× compression** on long code QA tasks while preserving performance.
- Maintains **syntactic validity** better than token-level pruning (line-level granularity).
- **Low latency overhead** due to 0.6B model.

**Limitations (from paper):**
- Focused mainly on **Python repos**; multilingual evaluation is limited.
- Adds **extra model call** (skimmer) per large read.
- Risk of pruning context that is only indirectly relevant.
- Data generation depends on synthetic labels and LLM judgments.

### (c) How ctx-rm Differs / Improves
