"""BenchmarkRunner: orchestrates experiments across three session modes.

Session Modes:
  A. MINIMAL  — System prompt only. No accumulated context or noise.
  B. CTX_RM   — Full context (needles + noise) with eviction active.
  C. FULL     — Full context (needles + noise) with huge budget, no eviction.

Two runner implementations:
  - BenchmarkRunner (legacy): uses old AgentDriver (Gemini CLI, Claude Code)
  - AgentLoopRunner: uses new AgentLoop + ChatDriver (LlamaCpp, mock)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import orjson
import structlog

from ctx_rm.benchmarks.evaluator import Evaluator
from ctx_rm.benchmarks.executor import TurnContent, TurnExecutor, generate_noise
from ctx_rm.core.tokenizer import estimate_tokens
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
        run_index: int = 1,
    ) -> None:
        self.driver_name = driver_name
        self.task_id = task_id
        self.mode = mode
        self.token_budget = token_budget
        self.policy_name = policy_name
        self.output_dir = output_dir
        self.yaml_path = yaml_path
        self.fixtures_root = fixtures_root
        self.run_index = run_index

    async def run(self) -> None:
        """Execute the benchmark."""
        # Load task from YAML
        loader = TaskLoader(self.yaml_path)
        task = loader.get_task(self.task_id)

        # Resolve and create fixture working copy
        fixture_name = FixtureManager.resolve_fixture_name(task.repo_fixture)
        fm = FixtureManager(self.fixtures_root)
        working_copy = fm.create_working_copy(fixture_name)

        # Create nested output directory with run index
        if self.mode == "ctx-rm":
            result_dir = (
                self.output_dir / self.task_id / "ctx-rm" / self.driver_name
                / self.policy_name / f"run-{self.run_index}"
            )
        else:
            result_dir = (
                self.output_dir / self.task_id / self.mode / self.driver_name
                / f"run-{self.run_index}"
            )
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
            db_path=self.output_dir / f"{self.task_id}_{self.policy_name}_run{self.run_index}_store.db",
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
        config = CtxRmConfig()
        if self.driver_name == "gemini":
            return GeminiCLIDriver(model=config.gemini_model)
        elif self.driver_name == "claude":
            return ClaudeCodeDriver(model=config.claude_model)
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


# ── AgentLoopRunner ─────────────────────────────────────────────────────────


class AgentLoopRunner:
    """Benchmark runner using AgentLoop + ChatDriver (LlamaCpp or mock).

    Unlike BenchmarkRunner (which drives CLI agents per-turn), this runner
    delegates to AgentLoop which runs autonomously — the agent decides its
    own tool calls and turn count.

    Modes:
      MINIMAL: system prompt only, no noise, small budget
      FULL:    system prompt + needles + noise, huge budget (no eviction)
      CTX-RM:  system prompt + needles + noise, calibrated budget + eviction
    """

    # Budget for FULL mode — large enough that eviction never triggers
    FULL_BUDGET = 1_000_000

    def __init__(
        self,
        driver_name: str = "llamacpp",
        task_id: str = "CR-001",
        mode: str = "ctx-rm",
        token_budget: int = 100_000,
        policy_name: str = "budget",
        output_dir: Path = Path("./results"),
        yaml_path: Path = Path("docs/context_removal_benchmark_tasks.yaml"),
        fixtures_root: Path = Path("benchmarks/fixtures"),
        run_index: int = 1,
        max_turns: int = 30,
    ) -> None:
        self.driver_name = driver_name
        self.task_id = task_id
        self.mode = mode
        self.token_budget = token_budget
        self.policy_name = policy_name
        self.output_dir = output_dir
        self.yaml_path = yaml_path
        self.fixtures_root = fixtures_root
        self.run_index = run_index
        self.max_turns = max_turns

    async def run(self) -> None:
        """Load task, create fixture, run agent, evaluate."""
        from ctx_rm.agents.loop import AgentLoop, ChatDriver

        loader = TaskLoader(self.yaml_path)
        task = loader.get_task(self.task_id)

        fixture_name = FixtureManager.resolve_fixture_name(task.repo_fixture)
        fm = FixtureManager(self.fixtures_root)
        working_copy = fm.create_working_copy(fixture_name)

        try:
            result = await self.run_with_task(
                task=task,
                working_copy=working_copy,
            )
        finally:
            FixtureManager.cleanup(working_copy)

    async def run_with_task(
        self,
        task: "Task",
        working_copy: Path,
        driver_factory: Any = None,
    ) -> "AgentResult":
        """Run a benchmark against a pre-prepared task and working copy.

        Args:
            task: The loaded Task object.
            working_copy: Path to the fixture working directory.
            driver_factory: Optional callable returning a ChatDriver (for testing).
        """
        from ctx_rm.agents.loop import AgentLoop, AgentResult

        result_dir = self._result_dir()
        result_dir.mkdir(parents=True, exist_ok=True)

        metrics = MetricsCollector()

        # Create driver
        if driver_factory is not None:
            driver = driver_factory()
        else:
            driver = self._create_driver()

        # Create bus with mode-appropriate budget
        bus = self._create_bus()
        self._last_bus = bus  # Exposed for test inspection

        # Inject context (needles + noise) based on mode
        self._inject_context(bus, task)

        # Build system prompt and task instruction
        system_prompt = self._build_system_prompt(task)
        task_instruction = self._build_task_instruction(task, working_copy)

        # Create and run agent loop
        loop = AgentLoop(
            driver=driver,
            bus=bus,
            working_dir=str(working_copy),
            max_turns=self.max_turns,
        )

        result = await loop.run(system_prompt, task_instruction)

        # Run evaluation
        evaluator = Evaluator(working_copy)
        eval_result = evaluator.evaluate_task(self.task_id, task.evaluation)

        # Export metrics
        metrics.take_snapshot(bus.get_stats())
        metrics.export_json(result_dir / "metrics.json")

        # Export evaluation
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
            "agent_result": {
                "turns": result.turns,
                "tool_calls": result.tool_calls_made,
                "prompt_tokens": result.total_prompt_tokens,
                "completion_tokens": result.total_completion_tokens,
                "segments_evicted": result.segments_evicted,
            },
        }
        (result_dir / "evaluation.json").write_bytes(
            orjson.dumps(eval_data, option=orjson.OPT_INDENT_2)
        )

        logger.info(
            "agent_benchmark_complete",
            task=self.task_id,
            mode=self.mode,
            turns=result.turns,
            eval=eval_result.summary,
        )

        return result

    # ── System prompt ───────────────────────────────────────────────────

    def _build_system_prompt(self, task: "Task") -> str:
        """Build system prompt from task scenario only.

        Needles are NOT included here — they're injected as separate,
        evictable segments via _inject_context(). This ensures the eviction
        engine is actually tested against needle retention.
        """
        return "\n".join([
            "You are a coding agent. Complete the task using the available tools.",
            "",
            "## Task Scenario",
            task.scenario.strip(),
        ])

    def _build_task_instruction(self, task: "Task", working_copy: Path) -> str:
        """Build the user message that starts the agent."""
        return (
            f"Working directory: {working_copy}\n\n"
            f"{task.scenario.strip()}\n\n"
            "Use the available tools to complete this task. "
            "Read files to understand the codebase, then make the necessary changes."
        )

    # ── Context injection ──────────────────────────────────────────────

    def _inject_context(self, bus: ContextBus, task: "Task") -> None:
        """Inject needles and noise as evictable segments based on mode.

        MINIMAL: nothing injected (agent sees only system prompt + task)
        FULL and CTX-RM: needles + noise injected as CONTEXT segments
        """
        if self.mode == "minimal":
            return

        # Inject needles as evictable context segments
        for needle in task.needles:
            seg = Segment(
                content=needle.content,
                role=SegmentRole.CONTEXT,
                token_count=estimate_tokens(needle.content),
                source=f"needle:{needle.id}",
                metadata={
                    "openai_message": {
                        "role": "user",
                        "content": f"[context] {needle.content}",
                    },
                },
            )
            bus.ingest(seg)

        # Inject noise
        for injection in task.context_injections:
            noise = generate_noise(injection.size_tokens, injection.description)
            seg = Segment(
                content=noise,
                role=SegmentRole.CONTEXT,
                token_count=estimate_tokens(noise),
                source=f"noise:{injection.description}",
                metadata={
                    "openai_message": {
                        "role": "user",
                        "content": f"[context] {noise}",
                    },
                },
            )
            bus.ingest(seg)

    # ── Bus creation ───────────────────────────────────────────────────

    def _create_bus(self) -> ContextBus:
        """Create a ContextBus configured for the current mode."""
        from ctx_rm.core.embedding import HashingEmbeddingProvider

        if self.mode == "full":
            budget = self.FULL_BUDGET
        else:
            budget = self.token_budget

        store = TieredStore(
            embedding_provider=HashingEmbeddingProvider(),
        )
        policy = self._create_policy()
        scorer = self._create_scorer()

        return ContextBus(
            token_budget=budget,
            store=store,
            policy=policy,
            scorer=scorer,
        )

    # ── Driver creation ────────────────────────────────────────────────

    def _create_driver(self) -> Any:
        """Create the appropriate ChatDriver based on driver_name."""
        if self.driver_name == "llamacpp":
            from ctx_rm.drivers.llamacpp import LlamaCppDriver

            config = CtxRmConfig()
            return LlamaCppDriver(
                base_url=config.llama_base_url,
                temperature=config.llama_temperature,
                max_tokens=config.llama_max_tokens,
                timeout=config.llama_timeout,
            )
        else:
            raise ValueError(
                f"AgentLoopRunner only supports ChatDriver-compatible drivers, "
                f"got: {self.driver_name}"
            )

    # ── Result directory ───────────────────────────────────────────────

    def _result_dir(self) -> Path:
        if self.mode == "ctx-rm":
            return (
                self.output_dir / self.task_id / "ctx-rm" / self.driver_name
                / self.policy_name / f"run-{self.run_index}"
            )
        return (
            self.output_dir / self.task_id / self.mode / self.driver_name
            / f"run-{self.run_index}"
        )

    # ── Reuse helpers from BenchmarkRunner ─────────────────────────────

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
        # Source-aware scoring for ctx-rm mode: needles score higher than noise
        if self.mode == "ctx-rm":
            return HeuristicScorer(source_weight=0.3)
        return HeuristicScorer()
