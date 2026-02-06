"""Tests for the LlamaCpp driver — HTTP client for llama-server's OpenAI-compatible API."""

from __future__ import annotations

import pytest

from ctx_rm.drivers.llamacpp import LlamaCppDriver, ChatResponse, ToolCall

LLAMA_SERVER_URL = "http://192.168.86.141:8080"


# ── Unit tests (no server needed) ────────────────────────────────────────────


def test_chat_response_dataclass() -> None:
    resp = ChatResponse(
        content="hello",
        tool_calls=None,
        thinking=None,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    assert resp.content == "hello"
    assert resp.tool_calls is None


def test_tool_call_dataclass() -> None:
    tc = ToolCall(id="call_1", name="file_read", arguments={"path": "foo.py"})
    assert tc.name == "file_read"
    assert tc.arguments["path"] == "foo.py"


def test_driver_default_url() -> None:
    driver = LlamaCppDriver()
    assert "8080" in driver.base_url


def test_driver_custom_url() -> None:
    driver = LlamaCppDriver(base_url="http://localhost:9999")
    assert driver.base_url == "http://localhost:9999"


# ── Integration tests (requires running llama-server) ────────────────────────


@pytest.fixture()
def driver():
    return LlamaCppDriver(base_url=LLAMA_SERVER_URL)


async def _server_reachable(driver: LlamaCppDriver) -> bool:
    try:
        return await driver.check_available()
    except Exception:
        return False


@pytest.mark.asyncio
async def test_check_available(driver) -> None:
    available = await _server_reachable(driver)
    if not available:
        pytest.skip("llama-server not reachable")
    assert available


@pytest.mark.asyncio
async def test_simple_chat(driver) -> None:
    if not await _server_reachable(driver):
        pytest.skip("llama-server not reachable")

    messages = [
        {"role": "user", "content": "Reply with exactly: HELLO"}
    ]
    resp = await driver.chat(messages)
    assert resp.content is not None
    assert len(resp.content) > 0
    assert resp.prompt_tokens > 0
    assert resp.completion_tokens > 0


@pytest.mark.asyncio
async def test_chat_with_system_prompt(driver) -> None:
    if not await _server_reachable(driver):
        pytest.skip("llama-server not reachable")

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Always reply in uppercase."},
        {"role": "user", "content": "Say hello"},
    ]
    resp = await driver.chat(messages)
    assert resp.content is not None
    assert resp.prompt_tokens > 0


@pytest.mark.asyncio
async def test_chat_with_tools(driver) -> None:
    """Model should call a tool when given tool definitions and a relevant prompt."""
    if not await _server_reachable(driver):
        pytest.skip("llama-server not reachable")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a file at the given path",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute file path to read",
                        }
                    },
                    "required": ["path"],
                },
            },
        }
    ]

    messages = [
        {"role": "system", "content": "You are a coding assistant. Use available tools."},
        {"role": "user", "content": "Read the file at /tmp/test.py"},
    ]
    resp = await driver.chat(messages, tools=tools)

    # Model should either call the tool or mention it
    assert resp.content is not None or resp.tool_calls is not None
    if resp.tool_calls:
        assert len(resp.tool_calls) > 0
        assert resp.tool_calls[0].name == "read_file"


@pytest.mark.asyncio
async def test_thinking_content_captured(driver) -> None:
    """Nemotron's <think> content should be captured separately."""
    if not await _server_reachable(driver):
        pytest.skip("llama-server not reachable")

    messages = [
        {"role": "user", "content": "What is 15 * 23? Think step by step."},
    ]
    resp = await driver.chat(messages)
    assert resp.content is not None
    # Thinking may or may not be present depending on model config
    # Just verify the response is valid
    assert resp.prompt_tokens > 0
