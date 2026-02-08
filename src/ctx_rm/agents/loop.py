"""Agent loop: connects LlamaCpp driver + ToolExecutor + ContextBus.

Each message exchanged with the model becomes a Segment in the ContextBus.
When the bus evicts segments for budget enforcement, the corresponding
messages are removed from the conversation. Tool call/response pairs are
linked via pair_group and evicted together to maintain protocol integrity.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
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

# Progress callback: receives (event_name, data_dict)
ProgressCallback = Callable[[str, dict[str, Any]], None]


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
    recalls_made: int = 0


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
        enable_recall: bool = False,
        recall_top_k: int = 1,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.driver = driver
        self.bus = bus
        self.tool_executor = ToolExecutor(working_dir)
        self.max_turns = max_turns
        self.watcher_config = watcher_config
        self.enable_recall = enable_recall
        self.recall_top_k = recall_top_k
        self._on_progress = on_progress
        self._task_text: str = ""  # Set in run(), used as recall query
        self._recalls_made: int = 0
        self._recalled_ids: set[str] = set()  # Prevent recall thrashing

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Fire progress callback if registered."""
        if self._on_progress is not None:
            self._on_progress(event, data)

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
            self._task_text = task
            self._ingest_system(system_prompt)
            self._ingest_user(task)

            for turn in range(self.max_turns):
                self.bus.advance_turn()
                self._try_recall()

                self._emit("turn_start", {
                    "turn": turn + 1,
                    "active_segments": len(self.bus.active_segments),
                    "active_tokens": self.bus.active_tokens,
                })

                messages = self._render_messages()
                try:
                    response = await self.driver.chat(messages, tools=TOOL_DEFINITIONS)
                except Exception as e:
                    logger.error("agent_driver_chat_failed", turn=turn + 1, error=str(e))
                    return self._build_result(
                        None,
                        turn + 1,
                        total_prompt,
                        total_completion,
                        tool_calls_made,
                        watcher,
                    )

                total_prompt += response.prompt_tokens
                total_completion += response.completion_tokens

                if response.tool_calls:
                    pair_group = uuid.uuid4().hex[:8]
                    self._ingest_assistant_tool_calls(response, pair_group)

                    done_called = False
                    done_result: str | None = None

                    for tc in response.tool_calls:
                        self._emit("tool_call", {
                            "name": tc.name,
                            "args_preview": str(tc.arguments)[:120],
                        })
                        if tc.arguments.get("_malformed_json"):
                            raw = str(tc.arguments.get("_raw", ""))[:500]
                            result = (
                                "Error: malformed tool arguments JSON from model. "
                                "Retry the tool call with a valid JSON object. "
                                f"Raw arguments: {raw}"
                            )
                        else:
                            result = await self.tool_executor.execute(tc.name, tc.arguments)

                        self._ingest_tool_result(tc, result, pair_group)
                        tool_calls_made += 1

                        logger.info(
                            "turn_log",
                            turn=turn + 1,
                            tool=tc.name,
                            outcome_preview=result[:200],
                            tokens_prompt=response.prompt_tokens,
                            tokens_completion=response.completion_tokens,
                        )

                        if tc.name == "done":
                            done_called = True
                            done_result = result

                    self._cleanup_orphaned_pairs()
                else:
                    self._ingest_assistant_text(response)

                self._emit("turn_end", {
                    "turn": turn + 1,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
                })

                # Done tool terminates the loop immediately
                if response.tool_calls and done_called:
                    return self._build_result(
                        done_result, turn + 1,
                        total_prompt, total_completion, tool_calls_made,
                        watcher,
                    )

                if not response.tool_calls:
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

    # ── Recall ─────────────────────────────────────────────────────────

    # Sources safe for recall (no pair dependencies)
    _RECALLABLE_SOURCES = frozenset({"needle", "context", "user_task", "user_message"})

    def _try_recall(self) -> None:
        """Search evicted segments and recall relevant ones.

        Uses the task instruction as a search query against warm + cold tiers.
        Only recalls segments with safe sources (no assistant/tool pairs).
        Runs once per segment — recalled IDs are tracked to prevent thrashing.
        """
        if not self.enable_recall:
            return

        store_stats = self.bus.store.get_stats()
        if store_stats["warm_count"] + store_stats["cold_count"] == 0:
            return

        results = self.bus.search_evicted(self._task_text, top_k=self.recall_top_k)
        self._emit("recall_attempt", {
            "query": self._task_text[:120],
            "found_count": len(results),
        })
        for seg in results:
            # Skip already-recalled segments (prevent thrashing)
            if seg.seg_id in self._recalled_ids:
                continue

            # Only recall safe sources (skip assistant/tool — pair integrity)
            source_prefix = (seg.source or "").split(":")[0]
            if source_prefix not in self._RECALLABLE_SOURCES:
                continue

            recalled = self.bus.recall(seg.seg_id)
            if recalled is not None:
                self._recalls_made += 1
                self._recalled_ids.add(recalled.seg_id)
                logger.info(
                    "recall_triggered",
                    seg_id=recalled.seg_id,
                    source=recalled.source,
                    tokens=recalled.token_count,
                )

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
        assert response.tool_calls is not None
        tool_calls_data = []
        for tc in response.tool_calls:
            try:
                arguments = orjson.dumps(tc.arguments).decode()
            except Exception:
                logger.warning(
                    "assistant_tool_args_not_json_serializable",
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                )
                arguments = orjson.dumps({
                    "_malformed_json": True,
                    "_raw": str(tc.arguments),
                }).decode()

            tool_calls_data.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": arguments,
                },
            })

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
            recalls_made=self._recalls_made,
        )
