"""Agent loop: connects LlamaCpp driver + ToolExecutor + ContextBus.

Each message exchanged with the model becomes a Segment in the ContextBus.
When the bus evicts segments for budget enforcement, the corresponding
messages are removed from the conversation. Tool call/response pairs are
linked via pair_group and evicted together to maintain protocol integrity.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import orjson
import structlog

from ctx_rm.agents.tools import TOOL_DEFINITIONS, ToolExecutor
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.segment import Segment, SegmentRole
from ctx_rm.core.tokenizer import estimate_tokens
from ctx_rm.drivers.llamacpp import ChatResponse, ToolCall
from ctx_rm.watch.watcher import Watcher, WatcherConfig

logger = structlog.get_logger()


class ChatDriver(Protocol):
    """Protocol for chat drivers (enables mocking in tests)."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse: ...


@dataclass
class AgentResult:
    """Structured result from an agent loop run."""

    final_response: str | None
    turns: int
    total_prompt_tokens: int
    total_completion_tokens: int
    tool_calls_made: int
    segments_evicted: int
    bus_stats: dict[str, Any]
    watcher_stats: dict[str, Any] | None = None


class AgentLoop:
    """Agentic loop: driver + tools + ContextBus.

    Each message becomes a Segment in the ContextBus. When the bus evicts
    segments for budget enforcement, the corresponding messages are removed.
    Tool call/response pairs are linked via pair_group and evicted together.
    """

    def __init__(
        self,
        driver: ChatDriver,
        bus: ContextBus,
        working_dir: str,
        max_turns: int = 20,
        watcher_config: WatcherConfig | None = None,
    ) -> None:
        self.driver = driver
        self.bus = bus
        self.tool_executor = ToolExecutor(working_dir)
        self.max_turns = max_turns
        self.watcher_config = watcher_config

    async def run(self, system_prompt: str, task: str) -> AgentResult:
        """Run the agent loop to completion."""
        total_prompt = 0
        total_completion = 0
        tool_calls_made = 0

        # Start optional background watcher
        watcher: Watcher | None = None
        watcher_task: asyncio.Task | None = None
        if self.watcher_config is not None:
            watcher = Watcher(self.bus, self.watcher_config)
            watcher_task = asyncio.create_task(watcher.run())

        try:
            self._ingest_system(system_prompt)
            self._ingest_user(task)

            for turn in range(self.max_turns):
                self.bus.advance_turn()

                messages = self._render_messages()
                response = await self.driver.chat(messages, tools=TOOL_DEFINITIONS)

                total_prompt += response.prompt_tokens
                total_completion += response.completion_tokens

                if response.tool_calls:
                    pair_group = uuid.uuid4().hex[:8]
                    self._ingest_assistant_tool_calls(response, pair_group)

                    for tc in response.tool_calls:
                        result = await self.tool_executor.execute(tc.name, tc.arguments)
                        self._ingest_tool_result(tc, result, pair_group)
                        tool_calls_made += 1

                    self._cleanup_orphaned_pairs()
                else:
                    self._ingest_assistant_text(response)
                    return self._build_result(
                        response.content, turn + 1,
                        total_prompt, total_completion, tool_calls_made,
                        watcher,
                    )

            return self._build_result(
                None, self.max_turns,
                total_prompt, total_completion, tool_calls_made,
                watcher,
            )
        finally:
            if watcher is not None:
                watcher.stop()
            if watcher_task is not None:
                await watcher_task

    # ── Rendering ────────────────────────────────────────────────────────

    def _render_messages(self) -> list[dict[str, Any]]:
        """Convert active segments to OpenAI-format messages.

        System messages are always placed first (OpenAI format requirement).
        All other messages preserve insertion order.
        """
        system = []
        rest = []
        for seg in self.bus.active_segments:
            msg = seg.metadata["openai_message"]
            if msg["role"] == "system":
                system.append(msg)
            else:
                rest.append(msg)
        return system + rest

    # ── Ingestion helpers ────────────────────────────────────────────────

    def _ingest_system(self, content: str) -> None:
        seg = Segment(
            content=content,
            role=SegmentRole.SYSTEM,
            token_count=estimate_tokens(content),
            pinned=True,
            source="system_prompt",
            metadata={"openai_message": {"role": "system", "content": content}},
        )
        self.bus.ingest(seg)

    def _ingest_user(self, content: str) -> None:
        seg = Segment(
            content=content,
            role=SegmentRole.USER,
            token_count=estimate_tokens(content),
            source="user_task",
            metadata={"openai_message": {"role": "user", "content": content}},
        )
        self.bus.ingest(seg)

    def _ingest_assistant_text(self, response: ChatResponse) -> None:
        content = response.content or ""
        seg = Segment(
            content=content,
            role=SegmentRole.ASSISTANT,
            token_count=estimate_tokens(content),
            source="assistant_response",
            metadata={"openai_message": {"role": "assistant", "content": content}},
        )
        self.bus.ingest(seg)

    def _ingest_assistant_tool_calls(
        self, response: ChatResponse, pair_group: str,
    ) -> None:
        tool_calls_data = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": orjson.dumps(tc.arguments).decode(),
                },
            }
            for tc in response.tool_calls
        ]

        msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": tool_calls_data,
        }

        # Token estimate from serialized tool calls
        token_text = orjson.dumps(tool_calls_data).decode()
        if response.content:
            token_text = response.content + "\n" + token_text

        seg = Segment(
            content=token_text,
            role=SegmentRole.ASSISTANT,
            token_count=estimate_tokens(token_text),
            source="assistant_tool_call",
            metadata={
                "openai_message": msg,
                "tool_calls": tool_calls_data,
                "pair_group": pair_group,
            },
        )
        self.bus.ingest(seg)

    def _ingest_tool_result(
        self, tool_call: ToolCall, result: str, pair_group: str,
    ) -> None:
        msg = {
            "role": "tool",
            "content": result,
            "tool_call_id": tool_call.id,
        }
        seg = Segment(
            content=result,
            role=SegmentRole.TOOL,
            token_count=estimate_tokens(result),
            source=f"tool:{tool_call.name}",
            metadata={
                "openai_message": msg,
                "tool_call_id": tool_call.id,
                "pair_group": pair_group,
            },
        )
        self.bus.ingest(seg)

    # ── Pair integrity ───────────────────────────────────────────────────

    def _cleanup_orphaned_pairs(self) -> None:
        """Remove orphaned tool-call/tool-result segments after eviction.

        A pair group is orphaned if the assistant (with tool_calls) or any
        of its tool results have been evicted. Both halves must be present
        for valid OpenAI message format.
        """
        groups: dict[str, list[Segment]] = {}
        for seg in self.bus.active_segments:
            pg = seg.metadata.get("pair_group")
            if pg is not None:
                groups.setdefault(pg, []).append(seg)

        orphans: list[Segment] = []
        for members in groups.values():
            assistant_segs = [s for s in members if "tool_calls" in s.metadata]
            tool_segs = [s for s in members if "tool_call_id" in s.metadata]

            if not assistant_segs or not tool_segs:
                orphans.extend(members)
                continue

            # Verify all expected tool results are present
            expected_ids: set[str] = set()
            for asst in assistant_segs:
                for tc in asst.metadata["tool_calls"]:
                    expected_ids.add(tc["id"])

            present_ids = {s.metadata["tool_call_id"] for s in tool_segs}
            if expected_ids != present_ids:
                orphans.extend(members)

        for seg in orphans:
            seg.evict(reason="orphaned_pair", policy="agent_loop")
            self.bus._evict_segment(seg)  # same package, tight coupling by design

        if orphans:
            logger.info("orphan_cleanup", count=len(orphans))

    # ── Result construction ──────────────────────────────────────────────

    def _build_result(
        self,
        final_response: str | None,
        turns: int,
        prompt_tokens: int,
        completion_tokens: int,
        tool_calls_made: int,
        watcher: Watcher | None = None,
    ) -> AgentResult:
        stats = self.bus.get_stats()
        store = stats["store_stats"]
        evicted = store["warm_count"] + store["cold_count"] + store["graveyard_count"]
        return AgentResult(
            final_response=final_response,
            turns=turns,
            total_prompt_tokens=prompt_tokens,
            total_completion_tokens=completion_tokens,
            tool_calls_made=tool_calls_made,
            segments_evicted=evicted,
            bus_stats=stats,
            watcher_stats=watcher.get_stats() if watcher is not None else None,
        )
