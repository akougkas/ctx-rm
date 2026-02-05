"""BenchmarkRunner: orchestrates experiments across three session modes.

Session Modes:
  A. MINIMAL  — Conservative context. Only the current turn's prompt and
                system instructions. Previous turns are discarded.
  B. CTX_RM   — Greedy ingest + background removal. The agent ingests
                everything, ctx-rm's ContextBus manages what stays active.
  C. FULL     — Greedy ingest, no management. All accumulated context is
                sent every turn (up to model limits). The baseline.

The runner:
  1. Loads a task definition from YAML
  2. Creates the appropriate driver (Gemini CLI or Claude Code)
  3. Initializes the ContextBus + policy + scorer + watcher (for mode B)
  4. Iterates through task turns, driving the agent and collecting metrics
  5. Exports results to JSON for analysis
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies import BudgetAwarePolicy, ClockPolicy, EvictionPolicy, LRUPolicy
from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.segment import Segment, SegmentRole
from ctx_rm.drivers.base import AgentDriver
from ctx_rm.drivers.claude import ClaudeCodeDriver
from ctx_rm.drivers.gemini import GeminiCLIDriver
from ctx_rm.telemetry.metrics import MetricsCollector
from ctx_rm.watch.watcher import Watcher, WatcherConfig

logger = structlog.get_logger()

# Rough token estimate: ~4 chars per token (conservative)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Quick token estimate without calling an API."""
    return max(1, len(text) // CHARS_PER_TOKEN)


class BenchmarkRunner:
    """Orchestrator for benchmark experiments."""

    def __init__(
        self,
        driver_name: str = "gemini",
        task_id: str = "CR-001",
        mode: str = "ctx-rm",
        token_budget: int = 100_000,
        policy_name: str = "budget",
        output_dir: Path = Path("./results"),
        working_dir: Path = Path("."),
    ) -> None:
        self.driver_name = driver_name
        self.task_id = task_id
        self.mode = mode
        self.token_budget = token_budget
        self.policy_name = policy_name
        self.output_dir = output_dir
        self.working_dir = working_dir

    async def run(self) -> None:
        """Execute the benchmark."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        result_file = self.output_dir / f"{self.task_id}_{self.mode}_{self.driver_name}.json"

        driver = self._create_driver()
        available = await driver.check_available()
        if not available:
            logger.error("driver_not_available", driver=self.driver_name)
            return

        metrics = MetricsCollector()

        if self.mode == "ctx-rm":
            await self._run_ctx_rm_mode(driver, metrics)
        elif self.mode == "minimal":
            await self._run_minimal_mode(driver, metrics)
        elif self.mode == "full":
            await self._run_full_mode(driver, metrics)
        else:
            logger.error("unknown_mode", mode=self.mode)
            return

        metrics.export_json(result_file)
        logger.info("benchmark_complete", result=str(result_file), summary=metrics.summary())

    # ── Mode Implementations ────────────────────────────────────────────

    async def _run_ctx_rm_mode(self, driver: AgentDriver, metrics: MetricsCollector) -> None:
        """Mode B: Greedy ingest + ctx-rm background removal."""
        store = TieredStore(db_path=self.output_dir / f"{self.task_id}_store.db")
        policy = self._create_policy()
        scorer = HeuristicScorer()

        bus = ContextBus(
            token_budget=self.token_budget,
            store=store,
            policy=policy,
            scorer=scorer,
            metrics=metrics,
        )

        watcher = Watcher(bus, WatcherConfig())
        watcher_task = asyncio.create_task(watcher.run())

        try:
            turns = self._load_task_turns()

            for i, turn_prompt in enumerate(turns):
                bus.advance_turn()
                metrics.set_turn(i + 1)

                # Ingest the turn prompt as a user segment
                user_seg = Segment(
                    content=turn_prompt,
                    role=SegmentRole.USER,
                    token_count=estimate_tokens(turn_prompt),
                    source=f"turn:{i + 1}",
                )
                bus.ingest(user_seg)

                # Render active context and invoke agent
                context_text = self._render_segments(bus.active_segments)
                response = await driver.invoke(
                    prompt=turn_prompt,
                    context=context_text,
                    working_dir=str(self.working_dir),
                )

                # Ingest the agent's response as an assistant segment
                if response.text:
                    assistant_seg = Segment(
                        content=response.text,
                        role=SegmentRole.ASSISTANT,
                        token_count=estimate_tokens(response.text),
                        source=f"agent_response:turn:{i + 1}",
                    )
                    bus.ingest(assistant_seg)

                metrics.record_agent_response({
                    "text_length": len(response.text),
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "tool_calls": response.tool_calls,
                    "success": response.success,
                })
                metrics.take_snapshot(bus.get_stats())

                logger.info(
                    "turn_complete",
                    turn=i + 1,
                    active_tokens=bus.active_tokens,
                    response_len=len(response.text),
                )
        finally:
            watcher.stop()
            await watcher_task
            store.close()

    async def _run_minimal_mode(self, driver: AgentDriver, metrics: MetricsCollector) -> None:
        """Mode A: Minimal context — only current turn + system prompt."""
        turns = self._load_task_turns()

        for i, turn_prompt in enumerate(turns):
            metrics.set_turn(i + 1)

            # No accumulated context — just the current prompt
            response = await driver.invoke(
                prompt=turn_prompt,
                working_dir=str(self.working_dir),
            )

            metrics.record_agent_response({
                "text_length": len(response.text),
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "tool_calls": response.tool_calls,
                "success": response.success,
            })

            logger.info("turn_complete", turn=i + 1, mode="minimal")

    async def _run_full_mode(self, driver: AgentDriver, metrics: MetricsCollector) -> None:
        """Mode C: Full context — accumulate everything, no eviction."""
        turns = self._load_task_turns()
        accumulated_context: list[str] = []

        for i, turn_prompt in enumerate(turns):
            metrics.set_turn(i + 1)

            accumulated_context.append(f"[Turn {i + 1} - User]: {turn_prompt}")

            # Send ALL accumulated context
            context_text = "\n\n".join(accumulated_context)
            response = await driver.invoke(
                prompt=turn_prompt,
                context=context_text,
                working_dir=str(self.working_dir),
            )

            if response.text:
                accumulated_context.append(f"[Turn {i + 1} - Agent]: {response.text}")

            metrics.record_agent_response({
                "text_length": len(response.text),
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "tool_calls": response.tool_calls,
                "success": response.success,
                "accumulated_context_chars": len(context_text),
            })

            logger.info(
                "turn_complete",
                turn=i + 1,
                mode="full",
                context_chars=len(context_text),
            )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _create_driver(self) -> AgentDriver:
        if self.driver_name == "gemini":
            return GeminiCLIDriver()
        elif self.driver_name == "claude":
            return ClaudeCodeDriver()
        else:
            raise ValueError(f"Unknown driver: {self.driver_name}")

    def _create_policy(self) -> EvictionPolicy:
        if self.policy_name == "lru":
            return LRUPolicy()
        elif self.policy_name == "clock":
            return ClockPolicy()
        elif self.policy_name == "budget":
            return BudgetAwarePolicy()
        else:
            raise ValueError(f"Unknown policy: {self.policy_name}")

    def _load_task_turns(self) -> list[str]:
        """Load task turns from the benchmark YAML.

        TODO: Implement full YAML task loading with needle injection.
        For now, returns a placeholder sequence for development.
        """
        return [
            f"This is turn {i + 1} of task {self.task_id}. "
            "Please examine the codebase and work on the task."
            for i in range(5)
        ]

    def _render_segments(self, segments: list[Segment]) -> str:
        """Render active segments into a context string for the agent."""
        parts: list[str] = []
        for seg in segments:
            prefix = f"[{seg.role.value}]"
            if seg.source:
                prefix += f" ({seg.source})"
            parts.append(f"{prefix}: {seg.content}")
        return "\n\n".join(parts)
