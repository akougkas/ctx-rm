# Codebase Concerns

**Analysis Date:** 2026-02-05

## Tech Debt

**Redundancy Score Not Implemented:**
- Issue: Content deduplication scoring is stubbed out with `TODO` comment
- Files: `src/ctx_rm/core/scorer.py:71`
- Impact: Duplicate segments (e.g., repeated file reads, identical tool outputs) are not detected, wasting active context tokens
- Fix approach: Implement content hashing or embedding-based similarity detection in `HeuristicScorer.score_batch()`. Could use MinHash for fast approximate deduplication or cosine similarity if embeddings are available.

**Keyword-Only Search in ColdStore:**
- Issue: `ColdStore.search()` uses naive SQLite `LIKE` matching instead of semantic search
- Files: `src/ctx_rm/core/graveyard.py:178-190`
- Impact: Recalled segments may not be relevant. Agent can't find semantically similar content that uses different wording. Limits usefulness of graveyard recall.
- Fix approach: Add embedding storage (BLOB column in SQLite) and cosine similarity search. See NEXT-STEPS.md Phase 2 for full plan.

**Placeholder Task Loading:**
- Issue: `BenchmarkRunner._load_task_turns()` returns hardcoded placeholder turns instead of loading from YAML
- Files: `src/ctx_rm/benchmarks/runner.py:248-258`
- Impact: Benchmark harness cannot execute real multi-turn tasks with needle injection. Blocks validation of ctx-rm effectiveness.
- Fix approach: Implement full YAML task loader as described in NEXT-STEPS.md Phase 1. Parse `docs/context_removal_benchmark_tasks.yaml` and return actual task turns.

**Empty Benchmark Fixtures Directory:**
- Issue: `benchmarks/fixtures/` directory exists but contains no fixture repos
- Files: `benchmarks/fixtures/` (empty)
- Impact: Cannot run benchmarks even after task loader is implemented. No codebases for agents to work on.
- Fix approach: Generate 10 mini-repo fixtures (CR-001 through CR-010) as specified in NEXT-STEPS.md Phase 1. Each fixture should match the task requirements in the YAML.

**Token Estimation vs. Actual Tokenization:**
- Issue: Uses crude `CHARS_PER_TOKEN = 4` heuristic instead of actual model tokenizer
- Files: `src/ctx_rm/benchmarks/runner.py:40-45`
- Impact: Token counts may be inaccurate, leading to premature or delayed eviction. Budget management is approximate only.
- Fix approach: Integrate model-specific tokenizers (e.g., `tiktoken` for Claude, Gemini's tokenizer API). Add caching to avoid re-tokenizing.

**No Test Coverage for Drivers:**
- Issue: Driver implementations (`gemini.py`, `claude.py`) have no tests
- Files: `tests/drivers/` (does not exist)
- Impact: Driver changes could break without detection. JSON parsing regressions go unnoticed.
- Fix approach: Add `tests/drivers/test_gemini.py` and `tests/drivers/test_claude.py` with fixture-based JSON parsing tests. Mock subprocess calls.

## Known Bugs

**None Detected:**
- No explicit bug reports or symptoms found in code inspection.
- All 30 unit tests pass.

## Security Considerations

**Subprocess Command Injection Risk:**
- Risk: Driver implementations use subprocess to invoke CLI tools. If prompt or context contains shell metacharacters, could lead to command injection.
- Files: `src/ctx_rm/drivers/gemini.py:51-80`, `src/ctx_rm/drivers/claude.py:52-85`
- Current mitigation: Using `asyncio.create_subprocess_exec()` with argument list (not shell=True), which provides some protection.
- Recommendations: Add explicit validation/escaping of prompt and context strings before passing to subprocess. Sanitize special characters. Add test cases with malicious input.

**Database Injection in ColdStore Search:**
- Risk: `ColdStore.search()` uses parameterized queries, but keyword search with `LIKE` could be vulnerable if query is not properly escaped
- Files: `src/ctx_rm/core/graveyard.py:183-189`
- Current mitigation: Using SQLite parameterized queries with `?` placeholders, which prevents SQL injection.
- Recommendations: Already safe. No action needed unless custom SQL is added.

**Gemini API Key Exposure:**
- Risk: LLM scorer (planned) will require Gemini API key. If key is hardcoded or logged, it could leak.
- Files: `src/ctx_rm/core/scorer.py` (future LLMScorer implementation)
- Current mitigation: Not yet implemented. Config uses environment variables (good practice).
- Recommendations: When implementing LLMScorer, load API key from environment only. Never log or print API keys. Use `.env` with `.gitignore` protection.

## Performance Bottlenecks

**Synchronous Scoring in Eviction Cycle:**
- Problem: `Scorer.score_batch()` is synchronous and runs in the main event loop
- Files: `src/ctx_rm/core/bus.py:126`, `src/ctx_rm/core/scorer.py:65-78`
- Cause: If LLM-based scoring is added, each eviction cycle would block on API calls
- Improvement path: Make `Scorer.score_batch()` async. Use `asyncio.gather()` for parallel batch scoring. Add result caching to avoid re-scoring unchanged segments.

**Linear Search in ZombieQueue:**
- Problem: `ZombieQueue.promote()` uses `deque.remove()` which is O(n)
- Files: `src/ctx_rm/core/graveyard.py:282-287`
- Cause: Python's deque doesn't support efficient random deletion
- Improvement path: Replace with OrderedDict (like WarmCache) for O(1) lookup and removal. Zombie queue is small (max 16 items) so current impact is minimal.

**Full Context Re-rendering Every Turn:**
- Problem: `BenchmarkRunner._render_segments()` rebuilds entire context string from scratch each turn
- Files: `src/ctx_rm/benchmarks/runner.py:260-268`
- Cause: Simple implementation for clarity
- Improvement path: Implement incremental rendering. Track changes (added/removed segments) and update context string differentially. Low priority unless benchmarks show significant time spent here.

## Fragile Areas

**Tiered Transition Logic:**
- Files: `src/ctx_rm/core/graveyard.py:312-378`
- Why fragile: Complex state machine with cascade transitions (Active→Warm→Cold→Graveyard) and recall path (Cold→Zombie→Active). Multiple methods touch the same data structures.
- Safe modification: Always update both the tier transition code and audit log simultaneously. Add integration tests for any new transition paths. Verify counts before and after transitions.
- Test coverage: Good (tests cover warm→cold cascade, recall paths, zombie staging). Add more edge case tests for simultaneous transitions.

**ContextBus Eviction Trigger:**
- Files: `src/ctx_rm/core/bus.py:114-115`
- Why fragile: Auto-eviction is triggered inline during ingest. If scoring or eviction fails, ingest fails. Recursive eviction risk if eviction itself triggers more eviction.
- Safe modification: Always test headroom calculation changes with boundary conditions (budget=0, headroom_ratio=0, headroom_ratio=1). Add protection against infinite eviction loops.
- Test coverage: Basic coverage exists. Add stress tests with rapid ingestion and varying budget sizes.

**Driver JSON Parsing:**
- Files: `src/ctx_rm/drivers/gemini.py:80-120`, `src/ctx_rm/drivers/claude.py:85-130`
- Why fragile: Depends on external CLI tool JSON output format. If `gemini` or `claude` CLI changes their JSON schema, parsing breaks silently or returns partial data.
- Safe modification: Parse with strict schema validation (Pydantic models for responses). Add schema version checks if CLI tools provide them. Test against multiple CLI versions.
- Test coverage: None. High priority to add.

## Scaling Limits

**In-Memory Warm Cache Size:**
- Current capacity: 50,000 tokens (configurable via `warm_max_tokens`)
- Limit: On 8GB system, could hold ~10-20MB of text comfortably. Beyond that, Python's memory overhead becomes significant.
- Scaling path: Current limit is reasonable for prototype. For production, add memory pressure monitoring and dynamic cache size adjustment. Consider using Redis for warm cache if scaling to multiple workers.

**SQLite ColdStore Concurrency:**
- Current capacity: Single-process, single-threaded writes
- Limit: SQLite's WAL mode supports concurrent reads but serializes writes. If multiple benchmark runs execute in parallel, writes will contend.
- Scaling path: Enable WAL mode (`PRAGMA journal_mode=WAL`). For multi-process benchmarking, use separate DB files per run. For production, consider PostgreSQL for ColdStore.

**Token Budget Size:**
- Current capacity: Defaults to 200K tokens
- Limit: Larger budgets (500K+) work fine but increase scoring overhead. Eviction cycle time grows linearly with active segment count.
- Scaling path: Implement incremental scoring (only score new segments + recently accessed). Add sampling-based eviction for very large active contexts (score random subset, evict lowest).

## Dependencies at Risk

**Gemini CLI (google-gemini/gemini-cli):**
- Risk: Pre-release tool, could have breaking changes or be deprecated
- Impact: All Gemini driver functionality breaks. Benchmarks fail.
- Migration plan: If deprecated, switch to Gemini SDK (`google-genai`) with custom agentic loop. Would require significant driver refactor. Alternative: use OpenAI-compatible proxy.

**Claude Code CLI:**
- Risk: Closed-source Anthropic tool, no public API stability guarantees
- Impact: All Claude driver functionality breaks. Benchmarks fail.
- Migration plan: If broken, switch to Anthropic API SDK with custom tool loop. Would require implementing file ops and bash execution as tools.

**Astral `uv` Package Manager:**
- Risk: Rapidly evolving tool, could have breaking CLI changes
- Impact: `uv sync` could fail, breaking dev setup
- Migration plan: Pin `uv` version in documentation. Fallback to `pip` + `venv` if `uv` becomes unstable.

## Missing Critical Features

**No Embedding-Based Semantic Search:**
- Problem: ColdStore search is keyword-only (see Tech Debt above)
- Blocks: Intelligent segment recall. Agent can't find relevant past context unless exact keywords match.

**No LLM-Based Relevance Scoring:**
- Problem: Only heuristic scoring available (recency + frequency + role). No understanding of content relevance to current task.
- Blocks: Optimal eviction decisions. High-value but old segments may be evicted incorrectly.

**No Fixture Generation or Task Loader:**
- Problem: Benchmark infrastructure is incomplete (see Tech Debt above)
- Blocks: End-to-end validation of ctx-rm effectiveness. Cannot measure token savings or task success impact.

**No MCP Server Interface:**
- Problem: ctx-rm cannot be invoked by agents as a tool
- Blocks: Real-time integration with agents. Currently only works in benchmark harness mode.

**No CLI Session Resumption:**
- Problem: Benchmark runner doesn't persist or resume sessions
- Blocks: Long-running benchmarks. If a run crashes, must restart from beginning.

## Test Coverage Gaps

**Driver Subprocess Invocation:**
- What's not tested: Actual subprocess execution, CLI tool availability, JSON parsing of real responses
- Files: `src/ctx_rm/drivers/gemini.py`, `src/ctx_rm/drivers/claude.py`
- Risk: Drivers could fail in production even with 100% unit test coverage of other components
- Priority: High

**Watcher Async Background Loop:**
- What's not tested: Watcher lifecycle (start, run, stop), eviction trigger timing, interaction with ContextBus during active agent turns
- Files: `src/ctx_rm/watch/watcher.py`
- Risk: Race conditions between watcher eviction and ingest. Background task could crash silently.
- Priority: High

**Benchmark Runner Integration:**
- What's not tested: End-to-end execution of `BenchmarkRunner` with mock drivers
- Files: `src/ctx_rm/benchmarks/runner.py`
- Risk: Integration failures between runner, bus, store, drivers. Config errors not caught until runtime.
- Priority: Medium

**ColdStore Embedding Storage:**
- What's not tested: Not yet implemented, but will need tests for BLOB serialization, cosine similarity calculation
- Files: `src/ctx_rm/core/graveyard.py` (future embedding support)
- Risk: Data corruption if embedding serialization is incorrect. Slow queries if index missing.
- Priority: Medium (future feature)

**Error Handling in Drivers:**
- What's not tested: Malformed JSON from CLI tools, subprocess timeout, CLI tool crashes
- Files: `src/ctx_rm/drivers/gemini.py`, `src/ctx_rm/drivers/claude.py`
- Risk: Unhandled exceptions crash benchmark runs. No graceful degradation.
- Priority: Medium

---

*Concerns audit: 2026-02-05*
