"""Validation: compare old chars/4 estimates vs tiktoken on real CR-001 data.

Uses the TurnExecutor to rebuild prompts and the response_log.jsonl for
response text. Verifies tiktoken is active and quantifies the error of
the old chars/4 approach.
"""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest

from ctx_rm.benchmarks.executor import TurnExecutor
from ctx_rm.benchmarks.loader import TaskLoader
from ctx_rm.core.tokenizer import _TIKTOKEN_AVAILABLE, estimate_tokens

YAML_PATH = Path("docs/context_removal_benchmark_tasks.yaml")
RESPONSE_LOG = Path("results/CR-001/minimal/gemini/run-1/response_log.jsonl")


@pytest.mark.skipif(not _TIKTOKEN_AVAILABLE, reason="tiktoken not installed")
class TestTiktokenActive:
    """Verify tiktoken is the active backend and produces accurate results."""

    def test_tiktoken_is_available(self) -> None:
        assert _TIKTOKEN_AVAILABLE

    def test_known_sentence(self) -> None:
        # cl100k_base: "The quick brown fox jumps over the lazy dog" = 9 tokens
        assert estimate_tokens("The quick brown fox jumps over the lazy dog") == 9

    def test_differs_from_chars4(self) -> None:
        """tiktoken should NOT produce identical results to chars/4 for code."""
        code = 'def estimate_tokens(text: str) -> int:\n    return len(text) // 4\n'
        tik = estimate_tokens(code)
        naive = max(1, len(code) // 4)
        assert tik != naive  # They should differ


@pytest.mark.skipif(not _TIKTOKEN_AVAILABLE, reason="tiktoken not installed")
class TestCR001PromptValidation:
    """Replay CR-001 turns and compare tokenizer estimates."""

    @pytest.fixture()
    def turns(self):
        task = TaskLoader(YAML_PATH).get_task("CR-001")
        return TurnExecutor().build_turns(task)

    def test_all_turns_tokenized(self, turns) -> None:
        for turn in turns:
            tokens = estimate_tokens(turn.prompt)
            assert tokens > 0
            # tiktoken should be within 3x of chars/4 (sanity check)
            naive = max(1, len(turn.prompt) // 4)
            assert tokens < naive * 3

    def test_noise_turn_tokens_reasonable(self, turns) -> None:
        """Turn 10 has ~2500 chars/4 tokens of noise (~10000 chars).

        tiktoken counts fewer tokens because common words tokenize efficiently.
        The old estimate was 2500, tiktoken gives ~1500.
        """
        turn_10 = turns[9]
        tokens = estimate_tokens(turn_10.prompt)
        assert tokens > 1000, f"Turn 10 should have >1000 ctx_tokens, got {tokens}"
        assert tokens < 3000, f"Turn 10 should have <3000 ctx_tokens, got {tokens}"

    def test_regular_turn_tokens_small(self, turns) -> None:
        """Regular turns (no noise/needle) should be <100 ctx_tokens."""
        turn_2 = turns[1]  # Turn 2: just base prompt
        tokens = estimate_tokens(turn_2.prompt)
        assert tokens < 100, f"Regular turn should have <100 ctx_tokens, got {tokens}"


@pytest.mark.skipif(
    not RESPONSE_LOG.exists(), reason="response_log.jsonl not found"
)
@pytest.mark.skipif(not _TIKTOKEN_AVAILABLE, reason="tiktoken not installed")
class TestResponseTextValidation:
    """Tokenize response texts from real Gemini runs."""

    @pytest.fixture()
    def entries(self):
        lines = RESPONSE_LOG.read_text().strip().splitlines()
        return [orjson.loads(line) for line in lines]

    def test_response_tokenization(self, entries) -> None:
        """Verify tiktoken produces consistent estimates for response text."""
        for entry in entries:
            resp = entry.get("response_text", "")
            if not resp:
                continue
            tik = estimate_tokens(resp)
            naive = max(1, len(resp) // 4)
            # tiktoken should give 0.5x to 2x of naive (wide sanity band)
            ratio = tik / naive
            assert 0.5 < ratio < 2.0, (
                f"Turn {entry['turn']}: ratio={ratio:.2f} (tik={tik}, naive={naive})"
            )

    def test_api_tokens_dwarf_ctx_tokens(self, entries) -> None:
        """API prompt_tokens should be >> our ctx_tokens estimate.

        This validates the core insight: API tokens include system prompt,
        tools, extensions — ctx-rm only manages a fraction of total context.
        """
        for entry in entries:
            api_pt = entry.get("prompt_tokens", 0)
            if api_pt == 0:
                continue  # timeout/failure
            prompt_len = entry["prompt_len"]
            ctx_tokens = estimate_tokens("x" * prompt_len)  # approximate
            assert api_pt > ctx_tokens * 10, (
                f"Turn {entry['turn']}: API tokens ({api_pt}) should be >> "
                f"ctx_tokens ({ctx_tokens})"
            )
