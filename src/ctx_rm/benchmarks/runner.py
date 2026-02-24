"""BenchmarkRunner: orchestrates experiments across three session modes.

Session Modes:
  A. MINIMAL  — System prompt only. No accumulated context or noise.
  B. CTX_RM   — Full context (needles + noise) with eviction active.
  C. FULL     — Full context (needles + noise) with huge budget, no eviction.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
import structlog

from ctx_rm.benchmarks.budget_map import ADMISSION_THRESHOLD, BUDGET_MAP
from ctx_rm.benchmarks.evaluator import Evaluator
from ctx_rm.benchmarks.executor import generate_noise
from ctx_rm.benchmarks.fixtures import FixtureManager
from ctx_rm.benchmarks.loader import TaskLoader
from ctx_rm.config import CtxRmConfig
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.adaptive import AdaptiveWeights
from ctx_rm.core.feedback import FeedbackTracker
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
from ctx_rm.core.tokenizer import estimate_tokens
from ctx_rm.telemetry.metrics import MetricsCollector

logger = structlog.get_logger()

if TYPE_CHECKING:
    from ctx_rm.agents.loop import AgentResult
    from ctx_rm.benchmarks.models import Task


def _task_goal_text(task: Task) -> str:
    """Build a semantic task goal string for scorer conditioning."""
    success = "; ".join(task.success_criteria[:3])
    return "\n".join(
        [
            f"Task: {task.title}",
            f"Scenario: {task.scenario.strip()}",
            f"Success criteria: {success}",
        ]
    )


class BenchmarkRunner:
    """Benchmark runner using AgentLoop + LlamaCppDriver.

    Delegates to AgentLoop which runs autonomously — the agent decides its
    own tool calls and turn count.

    Modes:
      MINIMAL: system prompt only, no noise, small budget
      FULL:    system prompt + needles + noise, huge budget (no eviction)
      CTX-RM:  system prompt + needles + noise, calibrated budget + eviction
    """

    FULL_BUDGET = 1_000_000
    DEFAULT_TOKEN_BUDGET = 100_000

    def __init__(
        self,
        driver_name: str = "llamacpp",
        task_id: str = "CR-001",
        mode: str = "ctx-rm",
        token_budget: int | None = None,
        policy_name: str = "budget",
        output_dir: Path = Path("./results"),
        yaml_path: Path = Path("docs/context_removal_benchmark_tasks.yaml"),
        fixtures_root: Path = Path("benchmarks/fixtures"),
        run_index: int = 1,
        max_turns: int = 30,
        enable_recall: bool = False,
        driver_temperature: float | None = None,
        on_bus_event: Any = None,
        on_loop_event: Any = None,
    ) -> None:
        self.driver_name = driver_name
        self.task_id = task_id
        self.mode = mode
        self.token_budget = token_budget
        self._explicit_budget = token_budget is not None
        self._resolved_budget: int | None = None
        self.policy_name = policy_name
        self.output_dir = output_dir
        self.yaml_path = yaml_path
        self.fixtures_root = fixtures_root
        self.run_index = run_index
        self.max_turns = max_turns
        self.enable_recall = enable_recall
        self.driver_temperature = driver_temperature
        self._on_bus_event = on_bus_event
        self._on_loop_event = on_loop_event
        self._task_goal = task_id

    async def run(self) -> None:
        """Load task, create fixture, run agent, evaluate."""

        loader = TaskLoader(self.yaml_path)
        task = loader.get_task(self.task_id)

        fixture_name = FixtureManager.resolve_fixture_name(task.repo_fixture)
        fm = FixtureManager(self.fixtures_root)
        working_copy = fm.create_working_copy(fixture_name)

        try:
            await self.run_with_task(
                task=task,
                working_copy=working_copy,
            )
        finally:
            FixtureManager.cleanup(working_copy)

    async def run_with_task(
        self,
        task: Task,
        working_copy: Path,
        driver_factory: Any = None,
    ) -> AgentResult:
        """Run a benchmark against a pre-prepared task and working copy.

        Args:
            task: The loaded Task object.
            working_copy: Path to the fixture working directory.
            driver_factory: Optional callable returning a ChatDriver (for testing).
        """
        from ctx_rm.agents.loop import AgentLoop

        result_dir = self._result_dir()
        result_dir.mkdir(parents=True, exist_ok=True)

        self._task_goal = _task_goal_text(task)

        metrics = MetricsCollector()

        driver = driver_factory() if driver_factory is not None else self._create_driver()

        bus = self._create_bus(metrics=metrics)
        self._last_bus = bus

        turn_injections = self._build_turn_injections(task)

        system_prompt = self._build_system_prompt(task)
        task_instruction = self._build_task_instruction(task, working_copy)

        # Wrap loop event callback to also update metrics per turn
        def _loop_event_with_metrics(event: str, data: dict) -> None:
            if event == "turn_start":
                turn = int(data.get("turn", 0))
                self._inject_turn_context(bus, turn_injections, turn)
                metrics.set_turn(turn)
                metrics.take_snapshot(bus.get_stats())
            elif event == "turn_end":
                metrics.record_agent_response({
                    "prompt_tokens": data.get("prompt_tokens", 0),
                    "completion_tokens": data.get("completion_tokens", 0),
                })
            if self._on_loop_event:
                self._on_loop_event(event, data)

        loop = AgentLoop(
            driver=driver,
            bus=bus,
            working_dir=str(working_copy),
            max_turns=self.max_turns,
            min_turns=task.min_turns,
            enable_recall=self.enable_recall,
            on_progress=_loop_event_with_metrics,
        )

        result = await loop.run(system_prompt, task_instruction)

        evaluator = Evaluator(working_copy)
        eval_result = evaluator.evaluate_task(self.task_id, task.evaluation)

        # Final snapshot
        metrics.set_turn(result.turns)
        metrics.take_snapshot(bus.get_stats())
        metrics.export_json(result_dir / "metrics.json")

        eval_data = {
            "task_id": eval_result.task_id,
            "mode": self.mode,
            "policy": self.policy_name if self.mode == "ctx-rm" else None,
            "budget": self._resolve_budget(),
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
                "recalls_made": result.recalls_made,
            },
        }
        (result_dir / "evaluation.json").write_bytes(
            orjson.dumps(eval_data, option=orjson.OPT_INDENT_2)
        )

        logger.info(
            "benchmark_complete",
            task=self.task_id,
            mode=self.mode,
            turns=result.turns,
            eval=eval_result.summary,
        )

        return result

    # ── System prompt ───────────────────────────────────────────────────

    def _build_system_prompt(self, task: Task) -> str:
        return "\n".join([
            "You are a coding agent. Complete the assigned task using the available tools.",
            "",
            "## Workflow",
            "1. Read files to understand the codebase before making changes.",
            "2. For large files, use start_line and end_line to read specific sections.",
            "3. Use grep_search with include and max_results to find relevant code efficiently.",
            "4. After modifying a file, read back the changed section to verify your edit.",
            "5. When the task is complete, call the done tool with a summary of what you did.",
            "",
            "## Tool Tips",
            "- file_read: Use start_line/end_line for partial reads of large files.",
            "- grep_search: Use include='*.py' to filter by file type, max_results=10 to limit output.",
            "- file_patch: The old_text must be unique in the file. Read first to find the exact text.",
            "- run_shell: Check exit codes. A non-zero exit code means the command failed.",
            "- done: Call this when the task is complete. Include summary and files_changed.",
            "",
            "## Task Scenario",
            task.scenario.strip(),
        ])

    def _build_task_instruction(self, task: Task, working_copy: Path) -> str:
        return (
            f"Working directory: {working_copy}\n\n"
            f"{task.scenario.strip()}\n\n"
            "Use the available tools to complete this task. "
            "Read files to understand the codebase, then make the necessary changes."
        )

    # ── Context injection ──────────────────────────────────────────────

    def _build_turn_injections(self, task: Task) -> dict[int, list[Segment]]:
        """Build turn-indexed context injections from task definitions."""
        if self.mode == "minimal":
            return {}

        by_turn: dict[int, list[Segment]] = {}

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
            by_turn.setdefault(needle.injection_turn, []).append(seg)

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
            by_turn.setdefault(injection.turn, []).append(seg)

        return by_turn

    @staticmethod
    def _inject_turn_context(
        bus: ContextBus,
        turn_injections: dict[int, list[Segment]],
        turn: int,
    ) -> None:
        """Ingest all scheduled context segments for the current turn."""
        for seg in turn_injections.pop(turn, []):
            bus.ingest(seg)

    # ── Bus creation ───────────────────────────────────────────────────

    def _create_bus(self, metrics: MetricsCollector | None = None) -> ContextBus:
        from ctx_rm.core.embedding import HashingEmbeddingProvider

        budget = self._resolve_budget()

        store = TieredStore(
            embedding_provider=HashingEmbeddingProvider(),
        )
        config = CtxRmConfig()
        policy = self._create_policy()
        feedback = FeedbackTracker() if self.mode == "ctx-rm" else None
        adaptive = AdaptiveWeights() if self.mode == "ctx-rm" else None
        scorer = self._create_scorer(adaptive=adaptive)

        return ContextBus(
            token_budget=budget,
            store=store,
            policy=policy,
            scorer=scorer,
            metrics=metrics,
            eviction_batch_mode=config.eviction_batch_mode,
            adaptive_single_evict_max_utilization=config.adaptive_single_evict_max_utilization,
            admission_threshold=ADMISSION_THRESHOLD,
            feedback=feedback,
            adaptive=adaptive,
            on_event=self._on_bus_event,
        )

    def _resolve_budget(self) -> int:
        """Select the token budget for the current run.

        Priority:
          1. ``full`` mode -> FULL_BUDGET (no eviction)
          2. Explicit budget provided by user -> use as-is
          3. ``ctx-rm`` mode + task in BUDGET_MAP -> use calibrated budget
          4. Fall through to configured ``self.token_budget``
        """
        if self._resolved_budget is not None:
            return self._resolved_budget

        if self.mode == "full":
            budget = self.FULL_BUDGET
            source = "full_mode"
        elif self.mode == "ctx-rm" and not self._explicit_budget:
            mapped = BUDGET_MAP.get(self.task_id)
            if mapped is not None:
                budget = mapped
                source = "budget_map"
            else:
                budget = self.DEFAULT_TOKEN_BUDGET
                source = "default"
        else:
            budget = (
                self.token_budget
                if self.token_budget is not None
                else self.DEFAULT_TOKEN_BUDGET
            )
            source = "explicit" if self._explicit_budget else "default"

        self._resolved_budget = budget
        logger.info(
            "budget_selected",
            task=self.task_id,
            budget=budget,
            source=source,
        )
        return budget

    # ── Driver creation ────────────────────────────────────────────────

    def _create_driver(self) -> Any:
        if self.driver_name == "llamacpp":
            from ctx_rm.drivers.llamacpp import LlamaCppDriver

            config = CtxRmConfig()
            return LlamaCppDriver(
                base_url=config.llama_base_url,
                temperature=(
                    self.driver_temperature
                    if self.driver_temperature is not None
                    else config.llama_temperature
                ),
                max_tokens=config.llama_max_tokens,
                timeout=config.llama_timeout,
                max_retries=config.llama_max_retries,
                retry_base_delay=config.llama_retry_base_delay,
                retry_max_delay=config.llama_retry_max_delay,
                retry_jitter=config.llama_retry_jitter,
                auto_discover_context_window=config.llama_auto_discover_context_window,
                context_window=config.llama_context_window,
            )
        else:
            raise ValueError(f"Unknown driver: {self.driver_name}")

    # ── Result directory ───────────────────────────────────────────────

    def _result_dir(self) -> Path:
        budget = self._resolve_budget()
        if self.mode == "ctx-rm":
            # Include budget in path to prevent different budget levels
            # from overwriting each other in budget-sweep experiments.
            return (
                self.output_dir / self.task_id / "ctx-rm" / self.driver_name
                / self.policy_name / f"b{budget}" / f"run-{self.run_index}"
            )
        return (
            self.output_dir / self.task_id / self.mode / self.driver_name
            / f"run-{self.run_index}"
        )

    # ── Factories ─────────────────────────────────────────────────────

    def _create_policy(self) -> EvictionPolicy:
        if self.policy_name == "lru":
            return LRUPolicy()
        elif self.policy_name == "clock":
            return ClockPolicy()
        elif self.policy_name == "budget":
            return BudgetAwarePolicy()
        elif self.policy_name == "arc":
            return ARCPolicy(capacity_tokens=self._resolve_budget())
        elif self.policy_name == "innodb":
            return InnoDBPolicy(capacity_tokens=self._resolve_budget())
        else:
            raise ValueError(f"Unknown policy: {self.policy_name}")

    def _create_scorer(self, adaptive: AdaptiveWeights | None = None) -> Scorer:
        config = CtxRmConfig()
        if config.scorer == "ollama":
            from ctx_rm.integrations.ollama_scorer import OllamaScorer

            return OllamaScorer(
                host=config.ollama_host,
                model=config.ollama_model,
                max_concurrent=config.ollama_max_concurrent,
                task_goal=self._task_goal,
            )
        if config.scorer == "sequential":
            from ctx_rm.core.scorer_sequential import SequentialScorer
            scoring_fn = None
            if config.sequential_backend == "ollama":
                from ctx_rm.integrations.llm_scoring_backend import make_ollama_scoring_fn

                scoring_fn = make_ollama_scoring_fn(
                    host=config.sequential_backend_host,
                    model=config.sequential_backend_model,
                )

            fallback = (
                HeuristicScorer(source_weight=0.3)
                if self.mode == "ctx-rm"
                else HeuristicScorer()
            )
            return SequentialScorer(
                scoring_fn=scoring_fn,
                task_goal=self._task_goal,
                fallback=fallback,
                adaptive=adaptive,
            )
        if self.mode == "ctx-rm":
            return HeuristicScorer(source_weight=0.3)
        return HeuristicScorer()
