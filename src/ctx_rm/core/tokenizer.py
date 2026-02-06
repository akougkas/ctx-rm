"""Tokenizer: accurate token estimation for ctx-rm managed context.

ctx-rm manages 'ctx_tokens' — the text we inject as context into the LLM's
prompt. This is distinct from 'api_tokens' which include system prompt, tool
definitions, and other overhead outside our control.

Uses tiktoken (cl100k_base) when available, falls back to chars/4.
"""

from __future__ import annotations

try:
    import tiktoken

    _encoder = tiktoken.get_encoding("cl100k_base")
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _encoder = None
    _TIKTOKEN_AVAILABLE = False


def estimate_tokens(text: str) -> int:
    """Estimate token count for text we control.

    Uses tiktoken cl100k_base when available (accurate for GPT-4/Claude-class
    tokenizers). Falls back to len(text) // 4 when tiktoken is not installed.
    """
    if not text:
        return 0
    if _TIKTOKEN_AVAILABLE and _encoder is not None:
        return len(_encoder.encode(text))
    return max(1, len(text) // 4)
