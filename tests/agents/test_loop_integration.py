"""Integration test: AgentLoop against real llama-server on mini:8080.

Requires: llama-server running at http://192.168.86.141:8080
Mark: pytest -m integration
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ctx_rm.agents.loop import AgentLoop
from ctx_rm.benchmarks.models import (
    ContextInjection,
    FileContainsCheck,
    Needle,
    Task,
)
from ctx_rm.benchmarks.runner import AgentLoopRunner
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.segment import SegmentRole
from ctx_rm.drivers.llamacpp import LlamaCppDriver

LLAMA_URL = "http://192.168.86.141:8080"


@pytest.fixture()
async def driver():
    d = LlamaCppDriver(base_url=LLAMA_URL, temperature=0.3, max_tokens=2048)
    if not await d.check_available():
        pytest.skip("llama-server not available")
    return d


def _bus(budget: int = 8000) -> ContextBus:
    return ContextBus(
        token_budget=budget,
        store=TieredStore(),
        policy=LRUPolicy(),
        headroom_ratio=0.15,
    )


# ── Test 1: Simple text response (no tools needed) ──────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_simple_question(driver, tmp_path) -> None:
    """Model answers a factual question without using tools."""
    bus = _bus()
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=3)

    result = await loop.run(
        system_prompt="You are a concise assistant. Answer in one sentence. Do not use tools.",
        task="What is the capital of France?",
    )

    assert result.final_response is not None
    assert "paris" in result.final_response.lower()
    assert result.turns >= 1
    assert len(bus.active_segments) >= 3  # system + user + assistant


# ── Test 2: Tool use — read a file ──────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_read_tool(driver, tmp_path) -> None:
    """Model uses file_read tool to answer a question about file contents."""
    (tmp_path / "secret.txt").write_text("The answer is 42.\n")

    bus = _bus()
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=5)

    result = await loop.run(
        system_prompt="You are a helpful assistant. Use the file_read tool to read files when asked.",
        task=f"Read the file at {tmp_path}/secret.txt and tell me what the answer is.",
    )

    assert result.final_response is not None
    assert "42" in result.final_response
    assert result.tool_calls_made >= 1

    # Verify tool segments exist in the bus
    tool_segs = [s for s in bus.active_segments if s.role == SegmentRole.TOOL]
    assert len(tool_segs) >= 1


# ── Test 3: Tool use — run shell command ─────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_shell_tool(driver, tmp_path) -> None:
    """Model uses run_shell to execute a command."""
    bus = _bus()
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=5)

    result = await loop.run(
        system_prompt="You are a helpful assistant. Use the run_shell tool to run commands.",
        task="Use the run_shell tool to run 'echo hello_world' and tell me the output.",
    )

    assert result.final_response is not None
    assert "hello_world" in result.final_response.lower() or result.tool_calls_made >= 1


# ── Test 4: Multi-step tool use ──────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_step_tool_use(driver, tmp_path) -> None:
    """Model writes a file then reads it back."""
    bus = _bus()
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=8)

    result = await loop.run(
        system_prompt="You are a helpful coding assistant. Use tools to complete tasks.",
        task=(
            f"Write a file called {tmp_path}/greeting.txt containing 'Hello from ctx-rm!', "
            "then read it back and confirm the contents."
        ),
    )

    assert result.tool_calls_made >= 2
    assert result.turns >= 2
    # File should exist on disk
    greeting = tmp_path / "greeting.txt"
    assert greeting.exists()
    assert "Hello from ctx-rm!" in greeting.read_text()


# ── Test 5: Eviction under tight budget ──────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_eviction_with_real_model(driver, tmp_path) -> None:
    """Tight token budget triggers eviction during real agent interaction."""
    # Create a file with enough content to eat budget
    (tmp_path / "data.txt").write_text("line " * 200 + "\n")

    bus = _bus(budget=300)  # Very tight — forces eviction (target=255)
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=5)

    result = await loop.run(
        system_prompt="You are helpful. Use file_read to read files when asked.",
        task=f"Read {tmp_path}/data.txt and summarize it.",
    )

    # With 500 token budget, eviction should trigger after reading the file
    assert result.segments_evicted > 0
    assert bus.active_tokens <= bus.headroom_target
    # System prompt must survive (pinned)
    assert any(s.role == SegmentRole.SYSTEM for s in bus.active_segments)


# ── AgentLoopRunner integration tests ─────────────────────────────────


def _make_runner_task(fixture_dir: Path) -> Task:
    """Create a task that the agent can solve: write specific content to a file."""
    return Task(
        id="INTEG-001",
        title="integration_write_test",
        expected_winner="ctx-rm",
        eviction_pressure="gradual",
        min_turns=3,
        repo_fixture=str(fixture_dir),
        scenario=(
            "You must write a Python file called result.py in the working directory. "
            "The file must contain exactly this line: answer = 42"
        ),
        needles=[
            Needle(
                id="N1",
                type="fact",
                injection_turn=1,
                injection_method="doc_read",
                content="The variable must be named 'answer' and set to 42.",
                risk_if_evicted="Agent uses wrong variable name.",
            ),
        ],
        context_injections=[
            ContextInjection(
                turn=2,
                type="noise",
                size_tokens=200,
                description="Unrelated debug logs",
            ),
        ],
        success_criteria=["result.py contains answer = 42"],
        evaluation=[
            FileContainsCheck(
                check="file_contains",
                target="result.py",
                must_include="answer = 42",
            ),
        ],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runner_ctx_rm_mode(driver, tmp_path) -> None:
    """AgentLoopRunner ctx-rm mode: agent writes file, eval checks it."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    result_dir = tmp_path / "results"

    task = _make_runner_task(fixture_dir)
    runner = AgentLoopRunner(
        driver_name="llamacpp",
        task_id="INTEG-001",
        mode="ctx-rm",
        token_budget=10_000,
        policy_name="lru",
        output_dir=result_dir,
        max_turns=10,
    )

    result = await runner.run_with_task(
        task=task,
        working_copy=fixture_dir,
    )

    assert result is not None
    assert result.turns >= 1
    assert result.tool_calls_made >= 1

    # Evaluation output should exist
    eval_path = result_dir / "INTEG-001" / "ctx-rm" / "llamacpp" / "lru" / "run-1" / "evaluation.json"
    assert eval_path.exists()

    import orjson
    eval_data = orjson.loads(eval_path.read_bytes())
    # Agent should have written result.py with answer = 42
    if eval_data["all_passed"]:
        assert (fixture_dir / "result.py").exists()
        assert "answer = 42" in (fixture_dir / "result.py").read_text()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runner_minimal_mode(driver, tmp_path) -> None:
    """AgentLoopRunner minimal mode: no noise injected."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()

    task = _make_runner_task(fixture_dir)
    runner = AgentLoopRunner(
        driver_name="llamacpp",
        task_id="INTEG-001",
        mode="minimal",
        token_budget=10_000,
        output_dir=tmp_path / "results",
        max_turns=10,
    )

    result = await runner.run_with_task(
        task=task,
        working_copy=fixture_dir,
    )

    assert result is not None
    assert result.turns >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runner_full_mode(driver, tmp_path) -> None:
    """AgentLoopRunner full mode: huge budget, noise injected."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()

    task = _make_runner_task(fixture_dir)
    runner = AgentLoopRunner(
        driver_name="llamacpp",
        task_id="INTEG-001",
        mode="full",
        output_dir=tmp_path / "results",
        max_turns=10,
    )

    result = await runner.run_with_task(
        task=task,
        working_copy=fixture_dir,
    )

    assert result is not None
    assert result.turns >= 1
    # Full mode should have zero evictions (budget is 1M)
    assert result.segments_evicted == 0
