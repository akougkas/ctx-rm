"""LlamaCpp driver — HTTP client for llama-server's OpenAI-compatible API.

Unlike the subprocess-based drivers (Gemini CLI, Claude Code), this driver
maintains conversation state via a messages array and supports tool calling
natively. This enables ctx-rm to manage context *inside* the agent loop:
every message, tool call, and tool result is a Segment that the ContextBus
can score, evict, or recall.

Ref: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class ToolCall:
    """A tool/function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    """Parsed response from llama-server /v1/chat/completions."""

    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    thinking: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class LlamaCppDriver:
    """HTTP client for llama-server's OpenAI-compatible chat completions API.

    Designed for agentic use: supports multi-turn conversations, tool calling,
    and thinking/reasoning capture from Nemotron-3-Nano.
    """

    def __init__(
        self,
        base_url: str = "http://192.168.86.141:8080",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def check_available(self) -> bool:
        """Check if llama-server is reachable."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.base_url}/v1/models")
            return resp.status_code == 200

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Send a chat completion request to llama-server.

        Args:
            messages: OpenAI-format messages array.
            tools: OpenAI-format tool definitions.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.

        Returns:
            Parsed ChatResponse with content, tool_calls, and usage.
        """
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        logger.debug(
            "llamacpp_chat",
            n_messages=len(messages),
            has_tools=bool(tools),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        """Parse OpenAI-compatible chat completion response.

        Handles:
        - Plain text responses
        - Tool calls (function calling)
        - Thinking/reasoning content (<think>...</think>)
        """
        usage = data.get("usage", {})
        choices = data.get("choices", [])

        if not choices:
            return ChatResponse(
                content=None,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                raw=data,
            )

        message = choices[0].get("message", {})
        content = message.get("content")
        thinking = None

        # Extract thinking content if present
        if content and "<think>" in content:
            thinking, content = self._extract_thinking(content)

        # Parse tool calls
        tool_calls = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = self._parse_tool_calls(raw_tool_calls)

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            thinking=thinking,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            raw=data,
        )

    @staticmethod
    def _extract_thinking(content: str) -> tuple[str | None, str | None]:
        """Extract <think>...</think> reasoning from content.

        Returns (thinking, remaining_content).
        """
        think_start = content.find("<think>")
        think_end = content.find("</think>")

        if think_start == -1 or think_end == -1:
            return None, content

        thinking = content[think_start + 7 : think_end].strip()
        remaining = (content[:think_start] + content[think_end + 8 :]).strip()

        if not thinking:
            thinking = None
        if not remaining:
            remaining = None

        return thinking, remaining

    @staticmethod
    def _parse_tool_calls(raw_calls: list[dict]) -> list[ToolCall]:
        """Parse tool calls from OpenAI-format response."""
        calls = []
        for i, raw in enumerate(raw_calls):
            func = raw.get("function", {})
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")

            # Arguments may be a JSON string or already a dict
            if isinstance(args_raw, str):
                import orjson

                try:
                    arguments = orjson.loads(args_raw)
                except Exception:
                    arguments = {"_raw": args_raw}
            else:
                arguments = args_raw

            calls.append(ToolCall(
                id=raw.get("id", f"call_{i}"),
                name=name,
                arguments=arguments,
            ))
        return calls
