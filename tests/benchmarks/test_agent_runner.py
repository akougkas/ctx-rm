"""Tests for AgentLoopRunner — the new runner using AgentLoop + ChatDriver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ctx_rm.agents.loop import AgentResult
from ctx_rm.benchmarks.models import (
    ContextInjection,
    FileContainsCheck,
    Needle,
    Task,
)
from ctx_rm.drivers.llamacpp import ChatResponse, ToolCall


# ── Helpers ────────────────────────────────────────────────────────────────


class FakeChatDriver:
    """Chat driver that writes a file then returns, for eval to pass."""

    def __init__(self, working_dir: Path, responses: list[ChatResponse] | None = None) -> None:
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

    async def check_available(self) -> bool:
        return True


def _make_task(fixture_path: Path) -> Task:
    """Create a minimal task for testing."""
    return Task(
        id="TEST-001",
        title="test_task",
        expected_winner="ctx-rm",
        eviction_pressure="gradual",
        min_turns=5,
        repo_fixture=str(fixture_path),
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


# ── Tests ──────────────────────────────────────────────────────────────────


class TestAgentLoopRunner:
    """Test the AgentLoopRunner orchestration."""

    def test_system_prompt_contains_scenario_only(self, tmp_path: Path) -> None:
        """System prompt must NOT contain needle content — needles are evictable."""
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        task = _make_task(tmp_path)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
        )
        prompt = runner._build_system_prompt(task)
        assert "Fix the bug" in prompt  # scenario present
        assert "Critical Context" not in prompt  # no needle section
        assert "doc_read" not in prompt  # no injection_method
        for needle in task.needles:
            assert needle.content not in prompt  # no needle content

    def test_system_prompt_same_regardless_of_needles(self, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        task = _make_task(tmp_path)
        runner = AgentLoopRunner(driver_name="llamacpp", task_id="TEST-001", mode="ctx-rm")
        prompt_with = runner._build_system_prompt(task)

        task.needles = []
        prompt_without = runner._build_system_prompt(task)
        assert prompt_with == prompt_without

    def test_needles_injected_as_separate_bus_segments(self, tmp_path: Path) -> None:
        """Needles must appear as individual evictable segments on the bus."""
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        task = _make_task(tmp_path)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=100_000,
        )
        bus = runner._create_bus()
        runner._inject_context(bus, task)

        needle_segs = [s for s in bus.active_segments if "needle" in s.source]
        assert len(needle_segs) == len(task.needles)
        # Each needle segment carries the needle content
        assert task.needles[0].content in needle_segs[0].content

    def test_needle_segments_are_not_pinned(self, tmp_path: Path) -> None:
        """Needle segments must be evictable (pinned=False)."""
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        task = _make_task(tmp_path)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=100_000,
        )
        bus = runner._create_bus()
        runner._inject_context(bus, task)

        needle_segs = [s for s in bus.active_segments if "needle" in s.source]
        for seg in needle_segs:
            assert seg.pinned is False, f"Needle segment {seg.source} must not be pinned"

    def test_needle_segments_have_openai_message(self, tmp_path: Path) -> None:
        """Needle segments must have openai_message metadata for rendering."""
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        task = _make_task(tmp_path)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=100_000,
        )
        bus = runner._create_bus()
        runner._inject_context(bus, task)

        needle_segs = [s for s in bus.active_segments if "needle" in s.source]
        for seg in needle_segs:
            assert "openai_message" in seg.metadata
            msg = seg.metadata["openai_message"]
            assert msg["role"] == "user"
            assert task.needles[0].content in msg["content"]

    def test_minimal_mode_no_needles_no_noise(self, tmp_path: Path) -> None:
        """Minimal mode: zero injected segments (no needles, no noise)."""
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        task = _make_task(tmp_path)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="minimal",
            token_budget=100_000,
        )
        bus = runner._create_bus()
        runner._inject_context(bus, task)

        assert len(bus.active_segments) == 0

    @pytest.mark.asyncio
    async def test_ctx_rm_mode_runs_end_to_end(self, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        result_dir = tmp_path / "results"

        task = _make_task(fixture_dir)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=10_000,
            policy_name="lru",
            output_dir=result_dir,
        )

        result = await runner.run_with_task(
            task=task,
            working_copy=fixture_dir,
            driver_factory=lambda: FakeChatDriver(fixture_dir),
        )

        assert result is not None
        assert isinstance(result, AgentResult)
        assert result.turns >= 1

    @pytest.mark.asyncio
    async def test_minimal_mode_has_no_noise(self, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        result_dir = tmp_path / "results"

        task = _make_task(fixture_dir)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="minimal",
            token_budget=10_000,
            output_dir=result_dir,
        )

        # In minimal mode, no noise injected — bus should have fewer segments
        driver = FakeChatDriver(fixture_dir)
        result = await runner.run_with_task(
            task=task,
            working_copy=fixture_dir,
            driver_factory=lambda: driver,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_full_mode_has_huge_budget(self, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()

        task = _make_task(fixture_dir)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="full",
            output_dir=tmp_path / "results",
        )

        result = await runner.run_with_task(
            task=task,
            working_copy=fixture_dir,
            driver_factory=lambda: FakeChatDriver(fixture_dir),
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_evaluation_output_written(self, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        result_dir = tmp_path / "results"

        task = _make_task(fixture_dir)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=10_000,
            policy_name="lru",
            output_dir=result_dir,
        )

        await runner.run_with_task(
            task=task,
            working_copy=fixture_dir,
            driver_factory=lambda: FakeChatDriver(fixture_dir),
        )

        # Check that result directory was created with eval + metrics
        expected_dir = result_dir / "TEST-001" / "ctx-rm" / "llamacpp" / "lru" / "run-1"
        assert expected_dir.is_dir()
        assert (expected_dir / "evaluation.json").exists()
        assert (expected_dir / "metrics.json").exists()

    @pytest.mark.asyncio
    async def test_noise_injection_adds_segments(self, tmp_path: Path) -> None:
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()

        task = _make_task(fixture_dir)
        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="TEST-001",
            mode="ctx-rm",
            token_budget=100_000,
            output_dir=tmp_path / "results",
        )

        driver = FakeChatDriver(fixture_dir)
        bus = runner._create_bus()
        runner._inject_context(bus, task)

        # Noise + needle should have been injected
        noise_segs = [s for s in bus.active_segments if "noise" in s.source]
        assert len(noise_segs) == 1
        needle_segs = [s for s in bus.active_segments if "needle" in s.source]
        assert len(needle_segs) == 1

    @pytest.mark.asyncio
    async def test_tight_budget_triggers_eviction(self, tmp_path: Path) -> None:
        """With tight budget, eviction MUST fire during agent run."""
        from ctx_rm.benchmarks.runner import AgentLoopRunner

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()

        # Heavy noise: 2000 tokens. Budget: 500. Eviction guaranteed.
        task = Task(
            id="EVICT-001",
            title="eviction_pressure_test",
            expected_winner="ctx-rm",
            eviction_pressure="gradual",
            min_turns=3,
            repo_fixture=str(fixture_dir),
            scenario="Write 'hello' to output.txt.",
            needles=[
                Needle(
                    id="N1",
                    type="fact",
                    injection_turn=1,
                    injection_method="doc_read",
                    content="The file must contain 'hello'.",
                    risk_if_evicted="Agent writes wrong content.",
                ),
            ],
            context_injections=[
                ContextInjection(
                    turn=1, type="noise", size_tokens=2000,
                    description="Heavy noise payload",
                ),
            ],
            success_criteria=["output.txt contains hello"],
            evaluation=[
                FileContainsCheck(
                    check="file_contains",
                    target="output.txt",
                    must_include="hello",
                ),
            ],
        )

        runner = AgentLoopRunner(
            driver_name="llamacpp",
            task_id="EVICT-001",
            mode="ctx-rm",
            token_budget=500,
            policy_name="lru",
            output_dir=tmp_path / "results",
        )

        result = await runner.run_with_task(
            task=task,
            working_copy=fixture_dir,
            driver_factory=lambda: FakeChatDriver(fixture_dir),
        )

        assert result.segments_evicted > 0, (
            "Tight budget (500) with 2000 tokens of noise must trigger eviction"
        )
