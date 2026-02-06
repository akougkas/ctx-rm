"""Tests for GeminiCLIDriver._parse_json_output token field parsing.

Covers:
  - v0.27.2 JSON format (input/candidates fields)
  - Legacy JSON format (inputTokens/outputTokens fields)
  - Tool stats extraction
  - Non-JSON fallback
  - Empty/missing stats blocks
"""

from __future__ import annotations

import orjson

from ctx_rm.drivers.gemini import GeminiCLIDriver


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
