"""Tests for GeminiCLIDriver — parsing, invoke behavior, and error handling.

Covers:
  - v0.27.2 JSON format (input/candidates fields)
  - Legacy JSON format (inputTokens/outputTokens fields)
  - Tool stats extraction
  - Non-JSON fallback
  - Empty/missing stats blocks
  - Long prompt handling (--prompt= form)
  - Timeout kills subprocess
  - Stderr noise filtering (YOLO mode, etc.)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest

from ctx_rm.drivers.gemini import GeminiCLIDriver, _STDERR_NOISE_PATTERNS


def _parse(data: dict | str) -> "AgentResponse":
    """Helper: encode data to bytes and parse via GeminiCLIDriver."""
    driver = GeminiCLIDriver()
    if isinstance(data, str):
        return driver._parse_json_output(data.encode())
    return driver._parse_json_output(orjson.dumps(data))


def test_parse_json_v027_token_fields() -> None:
    """Gemini CLI v0.27.2 uses 'input' and 'candidates' for token counts."""
    data = {
        "response": "Hello world",
        "stats": {
            "models": {
                "gemini-2.5-pro": {
                    "tokens": {
                        "input": 150,
                        "candidates": 42,
                    }
                }
            }
        },
    }
    resp = _parse(data)
    assert resp.prompt_tokens == 150
    assert resp.completion_tokens == 42
    assert resp.total_tokens == 192
    assert resp.text == "Hello world"
    assert resp.success is True


def test_parse_json_legacy_token_fields() -> None:
    """Fallback: older Gemini CLI used 'inputTokens' and 'outputTokens'."""
    data = {
        "response": "Legacy format",
        "stats": {
            "models": {
                "gemini-2.5-flash": {
                    "tokens": {
                        "inputTokens": 200,
                        "outputTokens": 80,
                    }
                }
            }
        },
    }
    resp = _parse(data)
    assert resp.prompt_tokens == 200
    assert resp.completion_tokens == 80
    assert resp.total_tokens == 280


def test_parse_json_with_tool_stats() -> None:
    """Tool calls parsed from stats.tools.totalCalls."""
    data = {
        "response": "Used tools",
        "stats": {
            "models": {
                "m": {"tokens": {"input": 10, "candidates": 5}}
            },
            "tools": {
                "totalCalls": 7,
                "totalSuccess": 6,
            },
        },
    }
    resp = _parse(data)
    assert resp.tool_calls == 7
    assert resp.prompt_tokens == 10
    assert resp.completion_tokens == 5


def test_parse_json_invalid_returns_plain_text() -> None:
    """Non-JSON stdout falls back to plain text response."""
    driver = GeminiCLIDriver()
    resp = driver._parse_json_output(b"This is not JSON at all")
    assert resp.text == "This is not JSON at all"
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0
    assert resp.raw_json == {}


def test_parse_json_empty_stats() -> None:
    """JSON with no stats block produces zero tokens without error."""
    data = {"response": "No stats here"}
    resp = _parse(data)
    assert resp.text == "No stats here"
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0
    assert resp.total_tokens == 0
    assert resp.tool_calls == 0
    assert resp.success is True


def test_parse_json_multiple_models() -> None:
    """Token counts aggregate across multiple model entries."""
    data = {
        "response": "Multi-model",
        "stats": {
            "models": {
                "gemini-2.5-pro": {
                    "tokens": {"input": 100, "candidates": 20}
                },
                "gemini-2.5-flash": {
                    "tokens": {"input": 50, "candidates": 10}
                },
            }
        },
    }
    resp = _parse(data)
    assert resp.prompt_tokens == 150
    assert resp.completion_tokens == 30
    assert resp.total_tokens == 180


def test_parse_json_file_changes() -> None:
    """File modification stats are extracted when present."""
    data = {
        "response": "Modified files",
        "stats": {
            "models": {"m": {"tokens": {"input": 1, "candidates": 1}}},
            "files": {
                "totalLinesAdded": 10,
                "totalLinesRemoved": 3,
                "changedFiles": ["foo.py", "bar.py"],
            },
        },
    }
    resp = _parse(data)
    assert resp.files_modified == ["foo.py", "bar.py"]


def test_is_retryable() -> None:
    """_is_retryable detects transient error patterns."""
    assert GeminiCLIDriver._is_retryable("HTTP 429 Too Many Requests") is True
    assert GeminiCLIDriver._is_retryable("RESOURCE_EXHAUSTED: quota exceeded") is True
    assert GeminiCLIDriver._is_retryable("Rate limit exceeded") is True
    assert GeminiCLIDriver._is_retryable("Invalid API key") is False
    assert GeminiCLIDriver._is_retryable("Permission denied") is False


# ── Invoke behavior tests ────────────────────────────────────────────


def _make_mock_proc(stdout: bytes = b'{"response":"ok"}', stderr: bytes = b"", returncode: int = 0):
    """Create a mock subprocess with configurable output."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


@pytest.mark.asyncio
async def test_invoke_uses_concat_prompt_form() -> None:
    """Prompt is passed as --prompt=VALUE (single arg) to avoid yargs splitting."""
    driver = GeminiCLIDriver(model="gemini-3-flash-preview")
    mock_proc = _make_mock_proc()

    with patch("ctx_rm.drivers.gemini.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await driver.invoke("hello world")
        args = mock_exec.call_args[0]
        # Should use --prompt=VALUE form, not -p VALUE
        prompt_args = [a for a in args if a.startswith("--prompt=")]
        assert len(prompt_args) == 1
        assert prompt_args[0] == "--prompt=hello world"


@pytest.mark.asyncio
async def test_invoke_long_prompt_no_arg_split() -> None:
    """Long prompts (10K+ chars) use --prompt= form without breaking."""
    driver = GeminiCLIDriver()
    long_prompt = "x" * 15000
    mock_proc = _make_mock_proc()

    with patch("ctx_rm.drivers.gemini.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        resp = await driver.invoke(long_prompt)
        args = mock_exec.call_args[0]
        prompt_args = [a for a in args if a.startswith("--prompt=")]
        assert len(prompt_args) == 1
        assert len(prompt_args[0]) == len("--prompt=") + 15000
        assert resp.success is True


@pytest.mark.asyncio
async def test_invoke_null_bytes_stripped() -> None:
    """Null bytes in prompt are stripped before passing to CLI."""
    driver = GeminiCLIDriver()
    mock_proc = _make_mock_proc()

    with patch("ctx_rm.drivers.gemini.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await driver.invoke("hello\x00world")
        args = mock_exec.call_args[0]
        prompt_arg = [a for a in args if a.startswith("--prompt=")][0]
        assert "\x00" not in prompt_arg
        assert prompt_arg == "--prompt=helloworld"


@pytest.mark.asyncio
async def test_invoke_timeout_kills_process() -> None:
    """On timeout, the subprocess is killed and cleaned up."""
    driver = GeminiCLIDriver()
    mock_proc = AsyncMock()
    mock_proc.kill = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
    # After kill, communicate should succeed (reap zombie)
    mock_proc.wait = AsyncMock(return_value=1)

    with patch("ctx_rm.drivers.gemini.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("ctx_rm.drivers.gemini.asyncio.wait_for", side_effect=TimeoutError):
            resp = await driver.invoke("test", timeout=1)
            assert resp.success is False
            assert "Timeout" in (resp.error or "")
            mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_invoke_filters_yolo_stderr_noise() -> None:
    """YOLO mode and other Gemini CLI noise in stderr doesn't trigger retry/error."""
    driver = GeminiCLIDriver()
    yolo_noise = (
        "YOLO mode is enabled. All tool calls will be automatically approved.\n"
        "Approval mode overridden to \"default\" because the current folder is not trusted.\n"
        "Session cleanup disabled: Either maxAge or maxCount must be specified\n"
        "Loading extension: chrome-devtools-mcp\n"
    )
    mock_proc = _make_mock_proc(
        stdout=b'{"response":"ok","stats":{}}',
        stderr=yolo_noise.encode(),
        returncode=0,
    )

    with patch("ctx_rm.drivers.gemini.asyncio.create_subprocess_exec", return_value=mock_proc):
        resp = await driver.invoke("test")
        assert resp.success is True
        assert resp.text == "ok"


@pytest.mark.asyncio
async def test_invoke_yolo_noise_with_nonzero_exit_filters_noise() -> None:
    """Non-zero exit with ONLY noise in stderr → treated as filtered (not retried endlessly)."""
    driver = GeminiCLIDriver(max_retries=0)
    yolo_only = (
        "YOLO mode is enabled. All tool calls will be automatically approved.\n"
        "Approval mode overridden to \"default\"\n"
    )
    mock_proc = _make_mock_proc(
        stderr=yolo_only.encode(),
        returncode=1,
    )

    with patch("ctx_rm.drivers.gemini.asyncio.create_subprocess_exec", return_value=mock_proc):
        resp = await driver.invoke("test")
        # After filtering noise, if stderr is empty, it should still report the exit code
        assert resp.success is False


@pytest.mark.asyncio
async def test_invoke_real_error_not_filtered() -> None:
    """Genuine errors in stderr are preserved (not filtered as noise)."""
    driver = GeminiCLIDriver(max_retries=0)
    mock_proc = _make_mock_proc(
        stderr=b"Error: Invalid API key",
        returncode=1,
    )

    with patch("ctx_rm.drivers.gemini.asyncio.create_subprocess_exec", return_value=mock_proc):
        resp = await driver.invoke("test")
        assert resp.success is False
        assert "Invalid API key" in (resp.error or "")


def test_parse_json_with_stdout_noise_prefix() -> None:
    """Gemini CLI may print noise to stdout before the JSON object."""
    driver = GeminiCLIDriver()
    noisy_output = (
        'Skipping project agents due to untrusted folder.\n'
        '{"response":"hello","stats":{"models":{"gemini-3-flash-preview":'
        '{"tokens":{"input":51022,"candidates":1280}}}}}'
    )
    resp = driver._parse_json_output(noisy_output.encode())
    assert resp.text == "hello"
    assert resp.prompt_tokens == 51022
    assert resp.completion_tokens == 1280
    assert resp.success is True


def test_extract_json_from_noisy_stdout() -> None:
    """_extract_json finds JSON object surrounded by noise."""
    result = GeminiCLIDriver._extract_json('noise before {"key":"val"} noise after')
    # rfind(}) matches the last }, so "noise after" won't be included
    # but first { to last } captures the full object
    assert result == {"key": "val"}


def test_extract_json_returns_none_for_no_json() -> None:
    """_extract_json returns None when no JSON object found."""
    assert GeminiCLIDriver._extract_json("no json here") is None
    assert GeminiCLIDriver._extract_json("") is None


def test_strip_stderr_noise() -> None:
    """_strip_stderr_noise removes known Gemini CLI noise patterns."""
    driver = GeminiCLIDriver()
    noisy = (
        "YOLO mode is enabled. All tool calls will be automatically approved.\n"
        "Approval mode overridden to \"default\"\n"
        "Session cleanup disabled: Either maxAge or maxCount\n"
        "Loading extension: chrome-devtools-mcp\n"
        "Loading extension: conductor\n"
        "Loaded cached credentials.\n"
        "Error: real problem here\n"
    )
    cleaned = driver._strip_stderr_noise(noisy)
    assert "YOLO" not in cleaned
    assert "Approval mode" not in cleaned
    assert "Session cleanup" not in cleaned
    assert "Loading extension" not in cleaned
    assert "Loaded cached credentials" not in cleaned
    assert "real problem here" in cleaned
