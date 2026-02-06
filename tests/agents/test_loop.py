"""Tests for the agent loop."""

from __future__ import annotations

from typing import Any

import pytest

from ctx_rm.agents.loop import AgentLoop, AgentResult
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.segment import SegmentRole
from ctx_rm.drivers.llamacpp import ChatResponse, ToolCall
from ctx_rm.watch.watcher import WatcherConfig


# ── Helpers ──────────────────────────────────────────────────────────────


class MockDriver:
    """Mock LlamaCpp driver returning canned responses in sequence."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self._idx = 0
        self.call_log: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.call_log.append({"messages": list(messages), "tools": tools})
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


def _bus(budget: int = 10_000, headroom: float = 0.15) -> ContextBus:
    return ContextBus(
        token_budget=budget,
        store=TieredStore(),
        policy=LRUPolicy(),
        headroom_ratio=headroom,
    )


def _text(content: str, pt: int = 50, ct: int = 10) -> ChatResponse:
    return ChatResponse(
        content=content, prompt_tokens=pt, completion_tokens=ct,
        total_tokens=pt + ct,
    )


def _tool(name: str, args: dict, call_id: str = "call_0") -> ChatResponse:
    return ChatResponse(
        content=None,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        prompt_tokens=50, completion_tokens=10, total_tokens=60,
    )


# ── Basic flow ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_response_no_tools(tmp_path) -> None:
    bus = _bus()
    driver = MockDriver([_text("Hello!")])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path))

    result = await loop.run("You are helpful.", "Say hello")

    assert result.final_response == "Hello!"
    assert result.turns == 1
    assert result.tool_calls_made == 0
    assert len(bus.active_segments) == 3
    roles = [s.role for s in bus.active_segments]
    assert roles == [SegmentRole.SYSTEM, SegmentRole.USER, SegmentRole.ASSISTANT]


@pytest.mark.asyncio
async def test_tool_call_then_text(tmp_path) -> None:
    (tmp_path / "test.txt").write_text("hello world")
    bus = _bus()
    driver = MockDriver([
        _tool("file_read", {"path": str(tmp_path / "test.txt")}),
        _text("The file says hello world"),
    ])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path))

    result = await loop.run("You are helpful.", "Read test.txt")

    assert result.final_response == "The file says hello world"
    assert result.turns == 2
    assert result.tool_calls_made == 1
    # system + user + assistant(tc) + tool_result + assistant(text) = 5
    assert len(bus.active_segments) == 5


@pytest.mark.asyncio
async def test_multiple_tool_calls_one_turn(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")
    bus = _bus()
    multi = ChatResponse(
        content=None,
        tool_calls=[
            ToolCall(id="c0", name="file_read", arguments={"path": str(tmp_path / "a.txt")}),
            ToolCall(id="c1", name="file_read", arguments={"path": str(tmp_path / "b.txt")}),
        ],
        prompt_tokens=60, completion_tokens=20, total_tokens=80,
    )
    driver = MockDriver([multi, _text("both read")])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path))

    result = await loop.run("sys", "read both")

    assert result.turns == 2
    assert result.tool_calls_made == 2
    # system + user + assistant(2 tc) + tool_0 + tool_1 + assistant(text) = 6
    assert len(bus.active_segments) == 6


# ── Max turns ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_turns_terminates(tmp_path) -> None:
    bus = _bus()
    driver = MockDriver([_tool("run_shell", {"command": "echo hi"})])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=3)

    result = await loop.run("sys", "loop")

    assert result.turns == 3
    assert result.final_response is None
    assert result.tool_calls_made == 3


# ── Eviction ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_eviction_under_tight_budget(tmp_path) -> None:
    bus = _bus(budget=250, headroom=0.2)  # target=200

    responses = [
        _tool("run_shell", {"command": f"echo {'x' * 80}"}, call_id=f"c{i}")
        for i in range(5)
    ]
    responses.append(_text("done"))

    driver = MockDriver(responses)
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=6)

    result = await loop.run("You are a coding assistant.", "Do five tasks")

    assert result.segments_evicted > 0
    assert bus.active_tokens <= bus.headroom_target


@pytest.mark.asyncio
async def test_system_prompt_survives_eviction(tmp_path) -> None:
    bus = _bus(budget=250, headroom=0.2)

    responses = [
        _tool("run_shell", {"command": f"echo {'x' * 80}"}, call_id=f"c{i}")
        for i in range(5)
    ]
    responses.append(_text("done"))

    driver = MockDriver(responses)
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=6)

    await loop.run("You are a coding assistant.", "Do tasks")

    active_roles = [s.role for s in bus.active_segments]
    assert SegmentRole.SYSTEM in active_roles
    system_segs = [s for s in bus.active_segments if s.role == SegmentRole.SYSTEM]
    assert system_segs[0].pinned is True


# ── Message format ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_messages_have_openai_format(tmp_path) -> None:
    bus = _bus()
    driver = MockDriver([
        _tool("run_shell", {"command": "echo test"}),
        _text("result"),
    ])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path))

    await loop.run("system", "task")

    # First call: system + user
    first = driver.call_log[0]["messages"]
    assert first[0]["role"] == "system"
    assert first[1]["role"] == "user"

    # Second call: includes tool_calls assistant + tool result
    second = driver.call_log[1]["messages"]
    tc_msgs = [m for m in second if m.get("tool_calls")]
    assert len(tc_msgs) == 1
    assert tc_msgs[0]["role"] == "assistant"

    tr_msgs = [m for m in second if m["role"] == "tool"]
    assert len(tr_msgs) == 1
    assert "tool_call_id" in tr_msgs[0]


# ── Pair integrity ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_orphaned_pairs_after_eviction(tmp_path) -> None:
    bus = _bus(budget=300, headroom=0.2)  # target=240

    responses = [
        _tool("run_shell", {"command": f"echo {'y' * 80}"}, call_id=f"c{i}")
        for i in range(6)
    ]
    responses.append(_text("done"))

    driver = MockDriver(responses)
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path), max_turns=7)

    await loop.run("You are helpful.", "work")

    # Every pair_group in active must have both assistant and tool halves
    groups: dict[str, list] = {}
    for seg in bus.active_segments:
        pg = seg.metadata.get("pair_group")
        if pg is not None:
            groups.setdefault(pg, []).append(seg)

    for pg, members in groups.items():
        has_asst = any("tool_calls" in s.metadata for s in members)
        has_tool = any("tool_call_id" in s.metadata for s in members)
        assert has_asst and has_tool, f"Orphaned pair group: {pg}"


# ── Result structure ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_result_structure(tmp_path) -> None:
    bus = _bus()
    driver = MockDriver([_text("ok")])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path))

    result = await loop.run("sys", "task")

    assert isinstance(result, AgentResult)
    assert isinstance(result.final_response, str)
    assert isinstance(result.turns, int)
    assert isinstance(result.total_prompt_tokens, int)
    assert isinstance(result.total_completion_tokens, int)
    assert isinstance(result.tool_calls_made, int)
    assert isinstance(result.segments_evicted, int)
    assert isinstance(result.bus_stats, dict)
    assert "active_tokens" in result.bus_stats


# ── Watcher integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_watcher_runs_during_loop(tmp_path) -> None:
    """When watcher_config is provided, watcher runs and stops cleanly."""
    bus = _bus(budget=250, headroom=0.2)
    responses = [
        _tool("run_shell", {"command": f"echo {'x' * 80}"}, call_id=f"c{i}")
        for i in range(4)
    ]
    responses.append(_text("done"))

    driver = MockDriver(responses)
    watcher_cfg = WatcherConfig(interval_seconds=0.1)
    loop = AgentLoop(
        driver=driver, bus=bus, working_dir=str(tmp_path),
        max_turns=5, watcher_config=watcher_cfg,
    )

    result = await loop.run("sys", "task")
    assert result.final_response == "done"
    assert result.watcher_stats is not None
    assert "cycles_run" in result.watcher_stats


@pytest.mark.asyncio
async def test_no_watcher_by_default(tmp_path) -> None:
    """Without watcher_config, watcher_stats is None."""
    bus = _bus()
    driver = MockDriver([_text("ok")])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path))

    result = await loop.run("sys", "task")
    assert result.watcher_stats is None


# ── Message ordering ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_ordering_system_first(tmp_path) -> None:
    """System message must come first even when context pre-injected into bus.

    Reproduces the runner pattern: _inject_context() ingests segments
    before loop.run() ingests system+user. Without the ordering fix,
    the LLM sees [context, system, user] instead of [system, context, user].
    """
    from ctx_rm.core.segment import Segment
    from ctx_rm.core.tokenizer import estimate_tokens

    bus = _bus()

    # Simulate runner._inject_context() — inject before loop.run()
    needle = Segment(
        content="CRITICAL: port must be 9876",
        role=SegmentRole.CONTEXT,
        token_count=estimate_tokens("CRITICAL: port must be 9876"),
        source="needle:N1",
        metadata={
            "openai_message": {
                "role": "user",
                "content": "[context] CRITICAL: port must be 9876",
            },
        },
    )
    bus.ingest(needle)

    driver = MockDriver([_text("ok")])
    loop = AgentLoop(driver=driver, bus=bus, working_dir=str(tmp_path))

    await loop.run("You are a coding agent.", "Create config.json")

    # Check the messages actually sent to the driver
    sent = driver.call_log[0]["messages"]
    assert sent[0]["role"] == "system", (
        f"First message must be system, got: {sent[0]['role']}"
    )
