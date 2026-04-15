"""L3 live evaluation runner.

This is the narrow maintained live tier: run one real agent session through
ContextBus and report the resulting eviction, recall, and token statistics.
It is intentionally thinner than the retired benchmark harness, but it gives
the repo a real end-to-end eval surface instead of leaving L3 as a placeholder.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ctx_rm.agents.loop import AgentLoop, AgentResult, ChatDriver
from ctx_rm.config import CtxRmConfig
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.embedding import HashingEmbeddingProvider
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.arc import ARCPolicy
from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.policies.budget import BudgetAwarePolicy
from ctx_rm.core.policies.clock import ClockPolicy
from ctx_rm.core.policies.innodb import InnoDBPolicy
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.drivers.llamacpp import LlamaCppDriver
from ctx_rm.watch.watcher import TriggerMode, WatcherConfig


@dataclass
class L3RunConfig:
    """Inputs for one live L3 run."""

    working_dir: str
    system_prompt: str
    task: str
    token_budget: int = 8_000
    headroom_ratio: float = 0.15
    policy_name: str = "budget"
    max_turns: int = 20
    min_turns: int = 1
    enable_recall: bool = False
    recall_top_k: int = 1
    recall_budget: int = 3
    watcher_mode: str = "off"
    watcher_interval_seconds: float = 5.0
    watcher_threshold_ratio: float = 0.70
    driver_base_url: str | None = None
    driver_temperature: float | None = None
    driver_max_tokens: int | None = None
    driver_timeout: float | None = None


def _policy_for_name(
    policy_name: str,
    token_budget: int,
) -> tuple[EvictionPolicy, HeuristicScorer | None]:
    if policy_name == "lru":
        return (LRUPolicy(), None)
    if policy_name == "clock":
        return (ClockPolicy(), None)
    if policy_name == "budget":
        return (BudgetAwarePolicy(), HeuristicScorer())
    if policy_name == "arc":
        return (ARCPolicy(capacity_tokens=token_budget), None)
    if policy_name == "innodb":
        return (InnoDBPolicy(capacity_tokens=token_budget), None)
    raise ValueError(f"unknown L3 policy: {policy_name}")


def _watcher_config(config: L3RunConfig) -> WatcherConfig | None:
    if config.watcher_mode == "off":
        return None
    return WatcherConfig(
        mode=TriggerMode(config.watcher_mode),
        interval_seconds=config.watcher_interval_seconds,
        threshold_ratio=config.watcher_threshold_ratio,
    )


async def run_live_eval(
    config: L3RunConfig,
    *,
    driver: ChatDriver | None = None,
) -> AgentResult:
    """Run one live agent session through the runtime stack."""
    defaults = CtxRmConfig()
    policy, scorer = _policy_for_name(config.policy_name, config.token_budget)
    store = TieredStore(
        embedding_provider=HashingEmbeddingProvider() if config.enable_recall else None
    )
    bus = ContextBus(
        token_budget=config.token_budget,
        store=store,
        policy=policy,
        scorer=scorer,
        headroom_ratio=config.headroom_ratio,
    )

    live_driver = driver or LlamaCppDriver(
        base_url=config.driver_base_url or defaults.llama_base_url,
        temperature=(
            config.driver_temperature
            if config.driver_temperature is not None
            else defaults.llama_temperature
        ),
        max_tokens=(
            config.driver_max_tokens
            if config.driver_max_tokens is not None
            else defaults.llama_max_tokens
        ),
        timeout=(
            config.driver_timeout
            if config.driver_timeout is not None
            else defaults.llama_timeout
        ),
        max_retries=defaults.llama_max_retries,
        retry_base_delay=defaults.llama_retry_base_delay,
        retry_max_delay=defaults.llama_retry_max_delay,
        retry_jitter=defaults.llama_retry_jitter,
        auto_discover_context_window=defaults.llama_auto_discover_context_window,
        context_window=defaults.llama_context_window,
    )

    loop = AgentLoop(
        driver=live_driver,
        bus=bus,
        working_dir=config.working_dir,
        max_turns=config.max_turns,
        min_turns=config.min_turns,
        watcher_config=_watcher_config(config),
        enable_recall=config.enable_recall,
        recall_top_k=config.recall_top_k,
        recall_budget=config.recall_budget,
    )
    return await loop.run(config.system_prompt, config.task)


def result_to_jsonable(result: AgentResult) -> dict:
    """Convert an AgentResult dataclass to a JSON-safe dict."""
    return asdict(result)
