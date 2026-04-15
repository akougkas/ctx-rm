"""L1 mechanism tier: pure-function replay of recorded traces through
ContextBus, without any live LLM. Deterministic, fast, CI-friendly.
"""

from ctx_rm.eval.l1_mechanism.metrics import L1Metrics, compute_metrics
from ctx_rm.eval.l1_mechanism.runner import L1Result, L1RunConfig, run_l1

__all__ = ["L1Metrics", "L1Result", "L1RunConfig", "compute_metrics", "run_l1"]
