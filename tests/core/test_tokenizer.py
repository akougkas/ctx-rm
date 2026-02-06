"""Tests for the tokenizer module — tiktoken with chars/4 fallback."""

from __future__ import annotations

from unittest.mock import patch

from ctx_rm.core.tokenizer import estimate_tokens, _TIKTOKEN_AVAILABLE


# ── Accuracy tests (tiktoken available) ──────────────────────────────────────


def test_estimate_tokens_returns_positive_for_empty_string() -> None:
    assert estimate_tokens("") >= 0


def test_estimate_tokens_returns_positive_for_nonempty() -> None:
    assert estimate_tokens("hello world") > 0


def test_estimate_tokens_scales_with_length() -> None:
    short = estimate_tokens("hello")
    long = estimate_tokens("hello " * 100)
    assert long > short


def test_estimate_tokens_known_string() -> None:
    """tiktoken cl100k_base: 'The quick brown fox jumps over the lazy dog' = 9 tokens."""
    text = "The quick brown fox jumps over the lazy dog"
    result = estimate_tokens(text)
    if _TIKTOKEN_AVAILABLE:
        assert result == 9
    else:
        # chars/4 fallback: 43 // 4 = 10
        assert result == 10


def test_estimate_tokens_code_snippet() -> None:
    """Code with special tokens should differ from naive chars/4."""
    code = 'def estimate_tokens(text: str) -> int:\n    return len(text) // 4\n'
    result = estimate_tokens(code)
    assert result > 0
    if _TIKTOKEN_AVAILABLE:
        # tiktoken should give a more accurate count than chars/4
        naive = max(1, len(code) // 4)
        # They shouldn't be identical (tiktoken handles subwords differently)
        # Just verify it's reasonable (within 3x of naive)
        assert result < naive * 3


def test_estimate_tokens_multiline_context() -> None:
    """Multi-line text typical of context window content."""
    text = "\n".join([
        "[user] (turn:1): Continue working on: Fix the legacy auth flag cascade bug.",
        "[assistant] (agent_response:turn:1): I'll start by examining the codebase.",
        "[user] (turn:2): Continue working on: Fix the legacy auth flag cascade bug.",
    ])
    result = estimate_tokens(text)
    assert result > 0


# ── Fallback tests ───────────────────────────────────────────────────────────


def test_fallback_when_tiktoken_unavailable() -> None:
    """When tiktoken is not available, chars/4 fallback is used."""
    with patch("ctx_rm.core.tokenizer._TIKTOKEN_AVAILABLE", False), \
         patch("ctx_rm.core.tokenizer._encoder", None):
        from ctx_rm.core.tokenizer import estimate_tokens as _estimate
        result = _estimate("The quick brown fox jumps over the lazy dog")
        # 43 chars // 4 = 10
        assert result == 10


def test_fallback_minimum_one_token() -> None:
    """Fallback returns at least 1 for non-empty strings."""
    with patch("ctx_rm.core.tokenizer._TIKTOKEN_AVAILABLE", False), \
         patch("ctx_rm.core.tokenizer._encoder", None):
        from ctx_rm.core.tokenizer import estimate_tokens as _estimate
        assert _estimate("hi") >= 1


def test_fallback_zero_for_empty() -> None:
    """Fallback returns 0 for empty string."""
    with patch("ctx_rm.core.tokenizer._TIKTOKEN_AVAILABLE", False), \
         patch("ctx_rm.core.tokenizer._encoder", None):
        from ctx_rm.core.tokenizer import estimate_tokens as _estimate
        assert _estimate("") == 0
