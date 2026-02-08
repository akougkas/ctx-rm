"""LlamaCpp driver — HTTP client for llama-server's OpenAI-compatible API.

Maintains conversation state via a messages array and supports tool calling
natively. This enables ctx-rm to manage context *inside* the agent loop:
every message, tool call, and tool result is a Segment that the ContextBus
can score, evict, or recall.

Ref: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
"""

from __future__ import annotations

import ast
import asyncio
import random
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from ctx_rm.core.tokenizer import estimate_tokens

logger = structlog.get_logger()

_TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

_CONTEXT_WINDOW_KEYS = (
    "n_ctx",
    "context_length",
    "max_context_length",
    "n_ctx_train",
)

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


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
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
        retry_max_delay: float = 8.0,
        retry_jitter: float = 0.25,
        auto_discover_context_window: bool = True,
        context_window: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.retry_jitter = retry_jitter
        self.auto_discover_context_window = auto_discover_context_window
        self.context_window = context_window
        self._context_window_refresh_attempted = context_window is not None

    async def check_available(self) -> bool:
        """Check if llama-server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/v1/models")
                if resp.status_code != 200:
                    return False

                if self.auto_discover_context_window:
                    self._update_context_window(resp.json())
                    self._context_window_refresh_attempted = True
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

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
        await self._maybe_refresh_context_window()

        requested_max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        effective_max_tokens = self._cap_max_tokens(messages, requested_max_tokens)

        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": effective_max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        logger.debug(
            "llamacpp_chat",
            n_messages=len(messages),
            has_tools=bool(tools),
            context_window=self.context_window,
            max_tokens=effective_max_tokens,
        )

        data: dict[str, Any] | None = None
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/v1/chat/completions",
                        json=payload,
                    )

                if resp.status_code in _TRANSIENT_STATUS_CODES and attempt < self.max_retries:
                    await self._sleep_before_retry(attempt, resp.status_code)
                    continue

                resp.raise_for_status()
                data = resp.json()
                break

            except (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
                httpx.TimeoutException,
                httpx.WriteError,
            ) as e:
                last_error = e
                if attempt >= self.max_retries:
                    raise
                await self._sleep_before_retry(attempt, type(e).__name__)

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in _TRANSIENT_STATUS_CODES and attempt < self.max_retries:
                    last_error = e
                    await self._sleep_before_retry(attempt, status)
                    continue
                raise

        if data is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("llama-server returned no response data")

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

        thinking: str | None = content[think_start + 7 : think_end].strip()
        remaining: str | None = (content[:think_start] + content[think_end + 8 :]).strip()

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

            arguments = LlamaCppDriver._parse_tool_arguments(args_raw)

            calls.append(ToolCall(
                id=raw.get("id", f"call_{i}"),
                name=name,
                arguments=arguments,
            ))
        return calls

    @staticmethod
    def _parse_tool_arguments(args_raw: Any) -> dict[str, Any]:
        """Parse tool arguments with recovery for malformed JSON strings."""
        import orjson

        if isinstance(args_raw, dict):
            return LlamaCppDriver._normalize_json_dict(args_raw)

        if not isinstance(args_raw, str):
            return {
                "_malformed_json": True,
                "_raw": str(args_raw),
            }

        text = args_raw.strip()
        if not text:
            return {}

        try:
            parsed = orjson.loads(text)
            if isinstance(parsed, dict):
                return LlamaCppDriver._normalize_json_dict(parsed)
            return {
                "_malformed_json": True,
                "_raw": text,
            }
        except Exception:
            pass

        # Recover common non-JSON patterns from model outputs:
        # - surrounding prose with embedded object
        # - trailing commas
        # - Python-style dict literals with single quotes
        json_candidate = text
        left = text.find("{")
        right = text.rfind("}")
        if left != -1 and right > left:
            json_candidate = text[left : right + 1]
        json_candidate = _TRAILING_COMMA_RE.sub(r"\1", json_candidate)

        try:
            parsed = orjson.loads(json_candidate)
            if isinstance(parsed, dict):
                return LlamaCppDriver._normalize_json_dict(parsed)
        except Exception:
            pass

        try:
            parsed = ast.literal_eval(json_candidate)
            if isinstance(parsed, dict):
                return LlamaCppDriver._normalize_json_dict(parsed)
        except Exception:
            pass

        return {
            "_malformed_json": True,
            "_raw": text,
        }

    @staticmethod
    def _normalize_json_dict(values: dict[Any, Any]) -> dict[str, Any]:
        """Coerce Python-literal dicts into JSON-serializable structures."""
        return {
            str(key): LlamaCppDriver._normalize_json_value(value)
            for key, value in values.items()
        }

    @staticmethod
    def _normalize_json_value(value: Any) -> Any:
        """Recursively normalize values so ``orjson.dumps`` can serialize them."""
        if isinstance(value, dict):
            return LlamaCppDriver._normalize_json_dict(value)

        if isinstance(value, (list, tuple)):
            return [LlamaCppDriver._normalize_json_value(item) for item in value]

        if isinstance(value, (set, frozenset)):
            # Deterministic ordering helps reproducible tests and logs.
            return [
                LlamaCppDriver._normalize_json_value(item)
                for item in sorted(value, key=repr)
            ]

        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", errors="replace")

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value

        return str(value)

    async def _maybe_refresh_context_window(self) -> None:
        """Discover context window and retry until a successful metadata fetch."""
        if self._context_window_refresh_attempted:
            return

        if not self.auto_discover_context_window:
            self._context_window_refresh_attempted = True
            return

        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 5.0)) as client:
                resp = await client.get(f"{self.base_url}/v1/models")
            if resp.status_code == 200:
                self._update_context_window(resp.json())
                self._context_window_refresh_attempted = True
        except Exception as e:
            logger.debug("llamacpp_context_window_discovery_failed", error=str(e))

    def _update_context_window(self, models_payload: dict[str, Any]) -> None:
        """Extract and store max context window from /v1/models payload."""
        context_window = self._extract_context_window(models_payload)
        if context_window is None:
            return

        self.context_window = context_window
        logger.debug("llamacpp_context_window_discovered", context_window=context_window)

    @staticmethod
    def _extract_context_window(models_payload: dict[str, Any]) -> int | None:
        """Extract the largest context window advertised by model metadata."""
        rows = models_payload.get("data", [])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            return None

        best: int | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue

            candidates: list[Any] = []
            for key in _CONTEXT_WINDOW_KEYS:
                candidates.append(row.get(key))

            metadata = row.get("metadata")
            if isinstance(metadata, dict):
                for key in _CONTEXT_WINDOW_KEYS:
                    candidates.append(metadata.get(key))

            model_info = row.get("model_info")
            if isinstance(model_info, dict):
                for key in _CONTEXT_WINDOW_KEYS:
                    candidates.append(model_info.get(key))

            for value in candidates:
                parsed = LlamaCppDriver._safe_positive_int(value)
                if parsed is None:
                    continue
                if best is None or parsed > best:
                    best = parsed
        return best

    @staticmethod
    def _safe_positive_int(value: Any) -> int | None:
        """Parse *value* as a positive integer when possible."""
        if value is None:
            return None
        try:
            ivalue = int(value)
        except (TypeError, ValueError):
            return None
        if ivalue <= 0:
            return None
        return ivalue

    def _cap_max_tokens(self, messages: list[dict[str, Any]], requested_max_tokens: int) -> int:
        """Cap completion tokens using discovered context window metadata."""
        if self.context_window is None:
            return requested_max_tokens

        prompt_tokens = self._estimate_prompt_tokens(messages)
        available = self.context_window - prompt_tokens
        if available <= 0:
            return 1
        return max(1, min(requested_max_tokens, available))

    @staticmethod
    def _estimate_prompt_tokens(messages: list[dict[str, Any]]) -> int:
        """Fast token estimate from message content and tool call payloads."""
        total = 0
        for msg in messages:
            total += estimate_tokens(str(msg.get("content", "")))

            if "tool_calls" in msg:
                try:
                    import orjson

                    total += estimate_tokens(orjson.dumps(msg["tool_calls"]).decode())
                except Exception:
                    total += estimate_tokens(str(msg["tool_calls"]))

            if "tool_call_id" in msg:
                total += estimate_tokens(str(msg["tool_call_id"]))

            role = msg.get("role")
            if isinstance(role, str):
                total += estimate_tokens(role)
        return total

    async def _sleep_before_retry(self, attempt: int, error: int | str) -> None:
        """Sleep using exponential backoff + jitter before retrying."""
        delay = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
        if self.retry_jitter > 0:
            delay += random.uniform(0.0, self.retry_jitter)
        logger.warning(
            "llamacpp_retry",
            attempt=attempt + 1,
            max_retries=self.max_retries,
            delay=round(delay, 3),
            error=error,
        )
        await asyncio.sleep(delay)
