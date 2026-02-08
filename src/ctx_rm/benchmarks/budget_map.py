"""Budget map: calibrated per-task token budgets and admission threshold.

Each budget is set to ~50% of the total injected context for that task
(needles + noise + overhead), ensuring 3+ eviction cycles when running
in ctx-rm mode.  Budgets were profiled from
``docs/context_removal_benchmark_tasks.yaml``.

ADMISSION_THRESHOLD is derived from the 75th percentile file size across
all three SCALE fixture directories (scale_codebase_nav,
scale_multi_refactor, scale_info_synthesis).  Files above this threshold
are routed to Warm on ingest instead of Active, preventing scan
pollution.
"""

from __future__ import annotations

# ── Per-task calibrated budgets ──────────────────────────────────────────
#
# Formula per task:
#   needle_tokens  = sum(len(needle.content) // 4 for each needle)
#   noise_tokens   = sum(injection.size_tokens for each injection)
#   overhead       = 300   (system prompt ~200 + task instruction ~100)
#   total          = needle_tokens + noise_tokens + overhead
#   budget         = int(total * 0.50)   (targeting 50% — centre of [40%, 60%])
#
# The 50% target guarantees that after all context is injected the bus
# will be at ~200% of budget, forcing multiple eviction cycles.

BUDGET_MAP: dict[str, int] = {
    # CR-series: original 10 tasks
    "CR-001": 1413,    # total=2826  (needles=26, noise=2500)
    "CR-002": 1056,    # total=2113  (needles=13, noise=1800)
    "CR-003": 2157,    # total=4314  (needles=14, noise=4000)
    "CR-004": 4157,    # total=8314  (needles=14, noise=8000)
    "CR-005": 3156,    # total=6313  (needles=13, noise=6000)
    "CR-006": 3657,    # total=7314  (needles=14, noise=7000)
    "CR-007": 1406,    # total=2812  (needles=12, noise=2500)
    "CR-008": 1156,    # total=2312  (needles=12, noise=2000)
    "CR-009": 1656,    # total=3312  (needles=12, noise=3000)
    "CR-010": 2656,    # total=5313  (needles=13, noise=5000)
    # MULTI / TRACE / SPEC tasks
    "MULTI-001": 1157,  # total=2315  (needles=15, noise=2000)
    "TRACE-001": 1657,  # total=3314  (needles=14, noise=3000)
    "SPEC-001": 1157,   # total=2315  (needles=15, noise=2000)
    # SCALE tasks — heavyweight fixtures
    "SCALE-001": 8667,   # total=17334  (needles=34, noise=17000)
    "SCALE-002": 12662,  # total=25325  (needles=25, noise=25000)
    "SCALE-003": 17677,  # total=35355  (needles=55, noise=35000)
}

# ── Admission threshold ─────────────────────────────────────────────────
#
# Derived from the 75th percentile of file sizes (in tokens, chars//4)
# across all files in the three SCALE fixture directories:
#
#   scale_codebase_nav   — 10 files
#   scale_multi_refactor — 12 files
#   scale_info_synthesis — 12 files
#
# 34 files total, sorted by token count:
#   P50 = 3356 tokens   (schema_validator.py)
#   P75 = 4024 tokens   (data_validator.py)
#   Max = 6261 tokens   (data_processor.py)
#
# Using P75 as threshold: files above 4024 tokens bypass Active and
# go straight to Warm, preventing large scan reads from polluting
# the working set.

ADMISSION_THRESHOLD: int = 4024
