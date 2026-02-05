# External Integrations

**Analysis Date:** 2026-02-05

## APIs & External Services

**AI/LLM Providers:**
- Gemini (Google) - Context removal coordination agent
  - SDK/Client: `google-genai` (optional dependency group `gemini`)
  - Auth: Via `gemini` CLI tool (uses system auth, no env var in code)
  - Invocation: Subprocess via `gemini -p <prompt> --output-format json`
  - Driver: `src/ctx_rm/drivers/gemini.py` (`GeminiCLIDriver`)
  - Models: gemini-2.5-pro (default), gemini-2.5-flash

- Claude (Anthropic) - Context removal coordination agent
  - SDK/Client: None (uses CLI tool `claude` installed via npm)
  - Auth: Via `claude` CLI tool (uses system auth, no env var in code)
  - Invocation: Subprocess via `claude -p <prompt> --output-format json`
  - Driver: `src/ctx_rm/drivers/claude.py` (`ClaudeCodeDriver`)
  - Models: sonnet (default), opus

**Future Integration:**
- LLM-based scoring: `google-genai` client for semantic scoring (planned, not yet implemented)
- Purpose: Replace heuristic scorer with LLM-based relevance assessment

## Data Storage

**Databases:**
- SQLite3 (embedded)
  - Connection: File path via `CTX_RM_DB_PATH` env var (default: `:memory:`)
  - Client: stdlib `sqlite3` module
  - Purpose: Cold storage tier for evicted segments (`TieredStore`)
  - Schema: `segments` table with `id, content, role, tier, score, tokens, created_at, accessed_at` columns
  - Location: `src/ctx_rm/core/graveyard.py` (`TieredStore._init_db()`)

**File Storage:**
- Local filesystem only
  - Results/benchmarks: `./results/` directory (configurable via `CTX_RM_OUTPUT_DIR`)
  - Metrics: JSON files written by `MetricsCollector` (`src/ctx_rm/telemetry/metrics.py`)
  - Benchmark fixtures: `benchmarks/fixtures/` (ignored in `.gitignore`)

**Caching:**
- In-memory only
  - Warm cache: `OrderedDict` LRU cache in `TieredStore` (max 64 segments, 50K tokens)
  - Active context: `OrderedDict` in `ContextBus` (main context window)
  - No external caching service (Redis, Memcached, etc.)

## Authentication & Identity

**Auth Provider:**
- None (system-level CLI auth only)
  - Gemini CLI and Claude CLI handle their own authentication
  - ctx-rm invokes these tools as subprocesses - no direct API credentials
  - Users must authenticate with `gemini auth login` or `claude login` separately

## Monitoring & Observability

**Error Tracking:**
- None (local only)

**Logs:**
- Structured logging via `structlog`
  - Level: Configurable via `CTX_RM_LOG_LEVEL` (default: INFO)
  - Output: Console (stderr)
  - Format: JSON-structured events with context fields
  - Key loggers: `src/ctx_rm/telemetry/metrics.py`, `src/ctx_rm/drivers/*.py`, `src/ctx_rm/watch/watcher.py`

**Metrics:**
- Custom metrics collection (`MetricsCollector`)
  - Location: `src/ctx_rm/telemetry/metrics.py`
  - Storage: JSON files in results directory
  - Tracked: tokens (active/warm/cold), evictions, recalls, budget usage, turns
  - Visualization: Via matplotlib in benchmark analysis scripts

## CI/CD & Deployment

**Hosting:**
- Not applicable (CLI tool, not hosted service)

**CI Pipeline:**
- None detected (no `.github/workflows/`, `.gitlab-ci.yml`, or similar)

## Environment Configuration

**Required env vars:**
- None strictly required (all have defaults in `src/ctx_rm/config.py`)

**Optional env vars (CTX_RM_* prefix):**
- `CTX_RM_TOKEN_BUDGET` - Max tokens in active context (default: 200000)
- `CTX_RM_POLICY` - Eviction policy: lru, clock, budget (default: budget)
- `CTX_RM_DB_PATH` - SQLite path for cold store (default: :memory:)
- `CTX_RM_DEFAULT_DRIVER` - Agent driver: gemini or claude (default: gemini)
- `CTX_RM_GEMINI_MODEL` - Gemini model selection (default: gemini-2.5-pro)
- `CTX_RM_CLAUDE_MODEL` - Claude model selection (default: sonnet)
- `CTX_RM_OUTPUT_DIR` - Results output directory (default: ./results)
- `CTX_RM_LOG_LEVEL` - Logging level (default: INFO)

**Secrets location:**
- Not managed by ctx-rm (delegated to CLI tools)
- Gemini/Claude credentials stored by their respective CLI tools in user's home directory

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

---

*Integration audit: 2026-02-05*
