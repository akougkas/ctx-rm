"""BenchmarkRunner: orchestrates experiments across three session modes.

Session Modes:
  A. MINIMAL  — Conservative context. Only the current turn's prompt and
                system instructions. Previous turns are discarded.
  B. CTX_RM   — Greedy ingest + background removal. The agent ingests
                everything, ctx-rm's ContextBus manages what stays active.
  C. FULL     — Greedy ingest, no management. All accumulated context is
                sent every turn (up to model limits). The baseline.

The runner:
  1. Loads a task definition from YAML via TaskLoader
  2. Creates a temp fixture copy via FixtureManager
  3. Creates the appropriate driver (Gemini CLI or Claude Code)
  4. Initializes the ContextBus + policy + scorer + watcher (for mode B)
  5. Builds turns via TurnExecutor with needle/noise injection
  6. Iterates through task turns, driving the agent and collecting metrics
  7. Runs Evaluator checks against the working copy
  8. Exports results to nested output: results/{task_id}/{mode}/{driver}/
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import orjson
import structlog

from ctx_rm.benchmarks.evaluator import Evaluator
from ctx_rm.benchmarks.executor import TurnContent, TurnExecutor
from ctx_rm.benchmarks.fixtures import FixtureManager
from ctx_rm.benchmarks.loader import TaskLoader
from ctx_rm.config import CtxRmConfig
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.embedding import HashingEmbeddingProvider
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies import (
    ARCPolicy,
    BudgetAwarePolicy,
    ClockPolicy,
    EvictionPolicy,
    InnoDBPolicy,
    LRUPolicy,
)
from ctx_rm.core.scorer import HeuristicScorer, Scorer
from ctx_rm.core.segment import Segment, SegmentRole
from ctx_rm.drivers.base import AgentDriver, AgentResponse
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
        yaml_path: Path = Path("docs/context_removal_benchmark_tasks.yaml"),
        fixtures_root: Path = Path("benchmarks/fixtures"),
    ) -> None:
        self.driver_name = driver_name
        self.task_id = task_id
        self.mode = mode
        self.token_budget = token_budget
        self.policy_name = policy_name
        self.output_dir = output_dir
        self.yaml_path = yaml_path
        self.fixtures_root = fixtures_root

    async def run(self) -> None:
        """Execute the benchmark."""
        # Load task from YAML
        loader = TaskLoader(self.yaml_path)
        task = loader.get_task(self.task_id)

        # Resolve and create fixture working copy
        fixture_name = FixtureManager.resolve_fixture_name(task.repo_fixture)
        fm = FixtureManager(self.fixtures_root)
        working_copy = fm.create_working_copy(fixture_name)

        # Create nested output directory
        result_dir = self.output_dir / self.task_id / self.mode / self.driver_name
        result_dir.mkdir(parents=True, exist_ok=True)

        # Build turns from task definition
        turns = TurnExecutor().build_turns(task)

        # Response log path
        log_path = result_dir / "response_log.jsonl"

        driver = self._create_driver()
        available = await driver.check_available()
        if not available:
            logger.error("driver_not_available", driver=self.driver_name)
            FixtureManager.cleanup(working_copy)
            return

        metrics = MetricsCollector()

        try:
            if self.mode == "ctx-rm":
                await self._run_ctx_rm_mode(driver, metrics, turns, working_copy, log_path)
            elif self.mode == "minimal":
                await self._run_minimal_mode(driver, metrics, turns, working_copy, log_path)
            elif self.mode == "full":
                await self._run_full_mode(driver, metrics, turns, working_copy, log_path)
            else:
                logger.error("unknown_mode", mode=self.mode)
                return

            # Run evaluation checks
            evaluator = Evaluator(working_copy)
            eval_result = evaluator.evaluate_task(self.task_id, task.evaluation)

            # Write metrics.json
            metrics.export_json(result_dir / "metrics.json")

            # Write evaluation.json
            eval_data = {
                "task_id": eval_result.task_id,
                "all_passed": eval_result.all_passed,
                "summary": eval_result.summary,
                "checks": [
                    {
                        "check_type": cr.check_type,
                        "target": cr.target,
                        "passed": cr.passed,
                        "detail": cr.detail,
                    }
                    for cr in eval_result.results
                ],
            }
            (result_dir / "evaluation.json").write_bytes(
                orjson.dumps(eval_data, option=orjson.OPT_INDENT_2)
            )

            logger.info(
                "benchmark_complete",
                result_dir=str(result_dir),
                evaluation=eval_result.summary,
                summary=metrics.summary(),
            )
        finally:
            FixtureManager.cleanup(working_copy)

    # ── Mode Implementations ────────────────────────────────────────────

    async def _run_ctx_rm_mode(
        self,
        driver: AgentDriver,
        metrics: MetricsCollector,
        turns: list[TurnContent],
        working_copy: Path,
        log_path: Path,
    ) -> None:
        """Mode B: Greedy ingest + ctx-rm background removal."""
        embedding_provider = HashingEmbeddingProvider()
        store = TieredStore(
            db_path=self.output_dir / f"{self.task_id}_store.db",
            embedding_provider=embedding_provider,
        )
        policy = self._create_policy()
        scorer = self._create_scorer()

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
            for turn in turns:
                bus.advance_turn()
                metrics.set_turn(turn.turn_number)

                # Ingest the turn prompt as a user segment
                user_seg = Segment(
                    content=turn.prompt,
                    role=SegmentRole.USER,
                    token_count=estimate_tokens(turn.prompt),
                    source=f"turn:{turn.turn_number}",
                )
                bus.ingest(user_seg)

                # Render active context and invoke agent
                context_text = self._render_segments(bus.active_segments)
                response = await driver.invoke(
                    prompt=turn.prompt,
                    context=context_text,
                    working_dir=str(working_copy),
                )

                # Ingest the agent's response as an assistant segment
                if response.text:
                    assistant_seg = Segment(
                        content=response.text,
                        role=SegmentRole.ASSISTANT,
                        token_count=estimate_tokens(response.text),
                        source=f"agent_response:turn:{turn.turn_number}",
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

                # Append response log entry
                self._append_log_entry(log_path, turn, response)

                logger.info(
                    "turn_complete",
                    turn=turn.turn_number,
                    active_tokens=bus.active_tokens,
                    response_len=len(response.text),
                )
        finally:
            watcher.stop()
            await watcher_task
            store.close()

    async def _run_minimal_mode(
        self,
        driver: AgentDriver,
        metrics: MetricsCollector,
        turns: list[TurnContent],
        working_copy: Path,
        log_path: Path,
    ) -> None:
        """Mode A: Minimal context — only current turn + system prompt."""
        for turn in turns:
            metrics.set_turn(turn.turn_number)

            # No accumulated context — just the current prompt
            response = await driver.invoke(
                prompt=turn.prompt,
                working_dir=str(working_copy),
            )

            metrics.record_agent_response({
                "text_length": len(response.text),
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "tool_calls": response.tool_calls,
                "success": response.success,
            })

            self._append_log_entry(log_path, turn, response)

            logger.info("turn_complete", turn=turn.turn_number, mode="minimal")

    async def _run_full_mode(
        self,
        driver: AgentDriver,
        metrics: MetricsCollector,
        turns: list[TurnContent],
        working_copy: Path,
        log_path: Path,
    ) -> None:
        """Mode C: Full context — accumulate everything, no eviction."""
        accumulated_context: list[str] = []

        for turn in turns:
            metrics.set_turn(turn.turn_number)

            accumulated_context.append(f"[Turn {turn.turn_number} - User]: {turn.prompt}")

            # Send ALL accumulated context
            context_text = "\n\n".join(accumulated_context)
            response = await driver.invoke(
                prompt=turn.prompt,
                context=context_text,
                working_dir=str(working_copy),
            )

            if response.text:
                accumulated_context.append(
                    f"[Turn {turn.turn_number} - Agent]: {response.text}"
                )

            metrics.record_agent_response({
                "text_length": len(response.text),
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "tool_calls": response.tool_calls,
                "success": response.success,
                "accumulated_context_chars": len(context_text),
            })

            self._append_log_entry(log_path, turn, response)

            logger.info(
                "turn_complete",
                turn=turn.turn_number,
                mode="full",
                context_chars=len(context_text),
            )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _create_driver(self) -> AgentDriver:
        if self.driver_name == "gemini":
            return GeminiCLIDriver()
        elif self.driver_name == "claude":
            return ClaudeCodeDriver()
        elif self.driver_name == "mock":
            from ctx_rm.drivers.mock import MockDriver

            return MockDriver()
        else:
            raise ValueError(f"Unknown driver: {self.driver_name}")

    def _create_policy(self) -> EvictionPolicy:
        if self.policy_name == "lru":
            return LRUPolicy()
        elif self.policy_name == "clock":
            return ClockPolicy()
        elif self.policy_name == "budget":
            return BudgetAwarePolicy()
        elif self.policy_name == "arc":
            return ARCPolicy(capacity_tokens=self.token_budget)
        elif self.policy_name == "innodb":
            return InnoDBPolicy(capacity_tokens=self.token_budget)
        else:
            raise ValueError(f"Unknown policy: {self.policy_name}")

    def _create_scorer(self) -> Scorer:
        config = CtxRmConfig()
        if config.scorer == "ollama":
            from ctx_rm.integrations.ollama_scorer import OllamaScorer

            return OllamaScorer(
                host=config.ollama_host,
                model=config.ollama_model,
                max_concurrent=config.ollama_max_concurrent,
                task_goal=self.task_id,
            )
        return HeuristicScorer()

    @staticmethod
    def _append_log_entry(
        log_path: Path, turn: TurnContent, response: AgentResponse
    ) -> None:
        """Append a single JSONL entry to the response log."""
        log_entry = {
            "turn": turn.turn_number,
            "prompt_len": len(turn.prompt),
            "response_text": response.text,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "tool_calls": response.tool_calls,
            "elapsed_ms": response.elapsed_ms,
            "success": response.success,
            "timestamp": time.time(),
        }
        with log_path.open("a") as f:
            f.write(orjson.dumps(log_entry).decode() + "\n")

    def _render_segments(self, segments: list[Segment]) -> str:
        """Render active segments into a context string for the agent."""
        parts: list[str] = []
        for seg in segments:
            prefix = f"[{seg.role.value}]"
            if seg.source:
                prefix += f" ({seg.source})"
            parts.append(f"{prefix}: {seg.content}")
        return "\n\n".join(parts)
