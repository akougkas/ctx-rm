"""Consolidated test harness for ctx-rm.

Single configurable test module covering:
- Mode smoke tests (minimal, ctx-rm, full)
- Policy eviction tests (lru, clock, budget, arc, innodb)
- Scorer differentiation tests (heuristic, sequential)
- Configurable benchmark tests from YAML
- Experiment A/B tests from YAML
- Regression: needle retention under eviction
- Live infrastructure tests (marked, skip without server)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ctx_rm.agents.loop import AgentLoop, AgentResult
from ctx_rm.benchmarks.models import (
    ContextInjection,
    FileContainsCheck,
    Needle,
    Task,
)
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.embedding import HashingEmbeddingProvider
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies import (
    ARCPolicy,
    BudgetAwarePolicy,
    ClockPolicy,
    InnoDBPolicy,
    LRUPolicy,
)
from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.scorer_sequential import SequentialScorer
from ctx_rm.core.segment import Segment, SegmentRole
from ctx_rm.core.tokenizer import estimate_tokens
from ctx_rm.drivers.llamacpp import ChatResponse, ToolCall


# ── Fixtures ──────────────────────────────────────────────────────────────


CONFIGS_DIR = Path(__file__).parent / "configs"


class MockDriver:
    """Mock chat driver returning canned responses."""

    def __init__(
        self, working_dir: Path, responses: list[ChatResponse] | None = None,
    ) -> None:
        self._working_dir = working_dir
        self._responses = responses or []
        self._idx = 0
        self.call_count = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.call_count += 1
        if self._responses:
            resp = self._responses[min(self._idx, len(self._responses) - 1)]
            self._idx += 1
            return resp
        # Default: write a file then return text
        if self.call_count == 1:
            return ChatResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_0",
                    name="file_write",
                    arguments={
                        "path": str(self._working_dir / "output.txt"),
                        "content": "test output content",
                    },
                )],
                prompt_tokens=50,
                completion_tokens=20,
                total_tokens=70,
            )
        return ChatResponse(
            content="Task complete.",
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
        )


def _make_task() -> Task:
    return Task(
        id="TEST-001",
        title="test_task",
        expected_winner="ctx-rm",
        eviction_pressure="gradual",
        min_turns=5,
        repo_fixture="inline",
        scenario="Fix the bug in output.txt by writing 'test output content'.",
        needles=[
            Needle(
                id="N1",
                type="fact",
                injection_turn=1,
                injection_method="doc_read",
                content="The output file must contain 'test output content'.",
                risk_if_evicted="Agent writes wrong content.",
            ),
        ],
        context_injections=[
            ContextInjection(
                turn=2,
                type="noise",
                size_tokens=500,
                description="Unrelated logs",
            ),
        ],
        success_criteria=["Output file contains expected content."],
        evaluation=[
            FileContainsCheck(
                check="file_contains",
                target="output.txt",
                must_include="test output content",
            ),
        ],
    )


def _seg(
    content: str = "filler",
    source: str = "noise",
    tokens: int = 100,
    pinned: bool = False,
) -> Segment:
    return Segment(
        content=content,
        role=SegmentRole.CONTEXT,
        token_count=tokens,
        source=source,
        pinned=pinned,
    )


def _make_bus(
    budget: int = 500,
    headroom: float = 0.1,
    policy: Any = None,
    scorer: Any = None,
) -> ContextBus:
    store = TieredStore(embedding_provider=HashingEmbeddingProvider())
    return ContextBus(
        token_budget=budget,
        store=store,
        policy=policy or LRUPolicy(),
        scorer=scorer,
        headroom_ratio=headroom,
    )


def _text(content: str, pt: int = 50, ct: int = 10) -> ChatResponse:
    return ChatResponse(
        content=content, prompt_tokens=pt, completion_tokens=ct,
        total_tokens=pt + ct,
    )


def _tool_resp(name: str, args: dict, call_id: str = "call_0") -> ChatResponse:
    return ChatResponse(
        content=None,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        prompt_tokens=50, completion_tokens=10, total_tokens=60,
    )


def _load_yaml_configs() -> list[dict[str, Any]]:
    """Load test configs from YAML files in tests/configs/."""
    configs = []
    if CONFIGS_DIR.is_dir():
        for yaml_file in sorted(CONFIGS_DIR.glob("*.yaml")):
            with yaml_file.open() as f:
                data = yaml.safe_load(f)
            for test_cfg in data.get("tests", []):
                test_cfg["_source"] = yaml_file.name
                configs.append(test_cfg)
    return configs


# ── Quick smoke tests (no LLM, mocked driver) ────────────────────────────


class TestModeRuns:
    """Each mode completes without error."""

    @pytest.mark.parametrize("mode", ["minimal", "ctx-rm", "full"])
    async def test_mode_runs(self, mode: str, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import BenchmarkRunner

        task = _make_task()
        budget = 100_000 if mode == "full" else 1500

        runner = BenchmarkRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode=mode,
            token_budget=budget,
            output_dir=tmp_path / "results",
            max_turns=3,
        )

        driver = MockDriver(tmp_path)
        result = await runner.run_with_task(
            task=task,
            working_copy=tmp_path,
            driver_factory=lambda: driver,
        )

        assert isinstance(result, AgentResult)
        assert result.turns >= 1


class TestPolicyEvicts:
    """Each policy evicts when over budget."""

    @pytest.mark.parametrize("policy_name,policy_cls", [
        ("lru", LRUPolicy),
        ("clock", ClockPolicy),
        ("budget", BudgetAwarePolicy),
        ("arc", ARCPolicy),
        ("innodb", InnoDBPolicy),
    ])
    def test_policy_evicts(self, policy_name: str, policy_cls: type) -> None:
        if policy_name in ("arc", "innodb"):
            policy = policy_cls(capacity_tokens=300)
        else:
            policy = policy_cls()

        bus = _make_bus(budget=300, headroom=0.1, policy=policy)

        # Ingest more than budget allows
        bus.ingest(_seg("a", tokens=150))
        bus.ingest(_seg("b", tokens=150))
        bus.ingest(_seg("c", tokens=150))

        assert bus.active_tokens <= bus.headroom_target
        assert bus.store.get_stats()["warm_count"] > 0


class TestScorerScores:
    """Each scorer produces different scores for needle vs noise."""

    @pytest.mark.parametrize("scorer_name", ["heuristic", "sequential"])
    def test_scorer_differentiates(self, scorer_name: str) -> None:
        if scorer_name == "heuristic":
            scorer = HeuristicScorer(source_weight=0.3)
        else:
            scorer = SequentialScorer(task_goal="Find the secret API key")

        needle = _seg("The secret API key is XYZ-123", source="needle:N1", tokens=50)
        noise = _seg("Random debug log output verbose", source="noise", tokens=50)

        scorer.score_batch([needle, noise], context=[needle, noise])

        assert needle.composite_score is not None
        assert noise.composite_score is not None
        assert needle.composite_score > noise.composite_score


# ── Configurable tests from YAML ─────────────────────────────────────────


_yaml_configs = _load_yaml_configs()
_bench_configs = [c for c in _yaml_configs if c.get("type") != "experiment"]
_experiment_configs = [c for c in _yaml_configs if c.get("type") == "experiment"]


class TestBenchmarkFromYaml:
    """Run benchmarks defined in YAML configs."""

    @pytest.mark.parametrize(
        "config",
        _bench_configs,
        ids=[c.get("name", f"yaml-{i}") for i, c in enumerate(_bench_configs)],
    )
    async def test_benchmark_from_yaml(
        self, config: dict[str, Any], tmp_path: Path,
    ) -> None:
        from ctx_rm.benchmarks.runner import BenchmarkRunner

        task = _make_task()
        mode = config.get("mode", "ctx-rm")
        budget = config.get("budget", 1500)
        max_turns = config.get("max_turns", 5)

        runner = BenchmarkRunner(
            driver_name="llamacpp",
            task_id=config.get("task", "TEST-001"),
            mode=mode,
            token_budget=budget,
            policy_name=config.get("policy", "budget"),
            output_dir=tmp_path / "results",
            max_turns=max_turns,
        )

        driver = MockDriver(tmp_path)
        result = await runner.run_with_task(
            task=task,
            working_copy=tmp_path,
            driver_factory=lambda: driver,
        )

        assert isinstance(result, AgentResult)
        assert result.turns >= 1


class TestExperimentFromYaml:
    """Run control vs challenger from experiment YAML."""

    @pytest.mark.parametrize(
        "config",
        _experiment_configs,
        ids=[c.get("name", f"exp-{i}") for i, c in enumerate(_experiment_configs)],
    )
    async def test_experiment_from_yaml(
        self, config: dict[str, Any], tmp_path: Path,
    ) -> None:
        from ctx_rm.benchmarks.runner import BenchmarkRunner

        task = _make_task()

        # Run control
        control = config.get("control", {})
        runner_ctrl = BenchmarkRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=control.get("budget", 1500),
            policy_name=control.get("policy", "budget"),
            output_dir=tmp_path / "results" / "control",
            max_turns=5,
        )
        driver_ctrl = MockDriver(tmp_path)
        result_ctrl = await runner_ctrl.run_with_task(
            task=task,
            working_copy=tmp_path,
            driver_factory=lambda: driver_ctrl,
        )

        # Run challenger
        challenger = config.get("challenger", {})
        runner_chal = BenchmarkRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=challenger.get("budget", 1500),
            policy_name=challenger.get("policy", "budget"),
            output_dir=tmp_path / "results" / "challenger",
            max_turns=5,
        )
        driver_chal = MockDriver(tmp_path)
        result_chal = await runner_chal.run_with_task(
            task=task,
            working_copy=tmp_path,
            driver_factory=lambda: driver_chal,
        )

        assert isinstance(result_ctrl, AgentResult)
        assert isinstance(result_chal, AgentResult)
        assert result_ctrl.turns >= 1
        assert result_chal.turns >= 1


# ── Regression: needle retention ──────────────────────────────────────────


class TestNeedleSurvivesEviction:
    """Needles are retained when noise is evicted (BudgetAwarePolicy + source_weight)."""

    def test_needle_survives(self) -> None:
        scorer = HeuristicScorer(source_weight=0.3)
        policy = BudgetAwarePolicy()
        bus = _make_bus(budget=300, headroom=0.1, policy=policy, scorer=scorer)

        needle = _seg("The API key is ABC123", source="needle:N1", tokens=80)
        bus.ingest(needle)

        bus.ingest(_seg("irrelevant debug logs", source="noise", tokens=80))
        bus.ingest(_seg("more verbose output", source="noise", tokens=80))
        bus.ingest(_seg("final noise", source="noise", tokens=80))

        active_ids = {s.seg_id for s in bus.active_segments}
        assert needle.seg_id in active_ids

    async def test_needle_recall_after_eviction(self, tmp_path: Path) -> None:
        """Evicted needle is recalled back to active with enable_recall."""
        bus = _make_bus(budget=200, headroom=0.2)

        needle_content = "CRITICAL: The config must contain port 9876"
        needle = Segment(
            content=needle_content,
            role=SegmentRole.CONTEXT,
            token_count=50,
            source="needle:N1",
            metadata={
                "openai_message": {
                    "role": "user",
                    "content": f"[context] {needle_content}",
                },
            },
        )
        bus.ingest(needle)
        needle_id = needle.seg_id

        noise = Segment(
            content="Unrelated debug logs and verbose output " * 10,
            role=SegmentRole.CONTEXT,
            token_count=100,
            source="noise:debug_logs",
            metadata={
                "openai_message": {
                    "role": "user",
                    "content": "[context] Unrelated debug logs " * 10,
                },
            },
        )
        bus.ingest(noise)

        driver = MockDriver(tmp_path, responses=[_text("Done.")])
        loop = AgentLoop(
            driver=driver,
            bus=bus,
            working_dir=str(tmp_path),
            max_turns=5,
            enable_recall=True,
        )

        result = await loop.run(
            "You are a coding agent.",
            "Create config.json with the correct port number.",
        )

        active_ids = {s.seg_id for s in bus.active_segments}
        assert needle_id in active_ids


# ── Event system tests ────────────────────────────────────────────────────


class TestEventCallbacks:
    """Verify event callback system works end-to-end."""

    def test_bus_events_fire(self) -> None:
        events: list[tuple[str, dict]] = []
        store = TieredStore()
        bus = ContextBus(
            token_budget=300,
            store=store,
            policy=LRUPolicy(),
            headroom_ratio=0.1,
            on_event=lambda name, data: events.append((name, data)),
        )

        bus.ingest(_seg("a", tokens=100))
        bus.advance_turn()
        bus.ingest(_seg("b", tokens=100))
        bus.ingest(_seg("c", tokens=150))  # triggers eviction

        event_names = [e[0] for e in events]
        assert "ingest" in event_names
        assert "turn_advance" in event_names
        assert "evict" in event_names

    async def test_loop_events_fire(self, tmp_path: Path) -> None:
        events: list[tuple[str, dict]] = []

        bus = _make_bus(budget=10_000)
        driver = MockDriver(tmp_path, responses=[
            _tool_resp("run_shell", {"command": "echo test"}),
            _text("done"),
        ])
        loop = AgentLoop(
            driver=driver,
            bus=bus,
            working_dir=str(tmp_path),
            max_turns=5,
            on_progress=lambda name, data: events.append((name, data)),
        )

        await loop.run("sys", "task")

        event_names = [e[0] for e in events]
        assert "turn_start" in event_names
        assert "turn_end" in event_names
        assert "tool_call" in event_names


# ── Live infrastructure tests ─────────────────────────────────────────────


@pytest.mark.integration
class TestLiveBench:
    """Run against real llama-server. Requires --run-integration or mark selection."""

    async def test_live_bench(self, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import BenchmarkRunner
        from ctx_rm.config import CtxRmConfig

        config = CtxRmConfig()
        from ctx_rm.drivers.llamacpp import LlamaCppDriver

        try:
            driver = LlamaCppDriver(base_url=config.llama_base_url)
            available = await driver.check_available()
        except Exception:
            available = False

        if not available:
            pytest.skip("llama-server not available")

        task = _make_task()
        runner = BenchmarkRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=1500,
            output_dir=tmp_path / "results",
            max_turns=5,
        )

        result = await runner.run_with_task(
            task=task,
            working_copy=tmp_path,
        )

        assert isinstance(result, AgentResult)
        assert result.turns >= 1
