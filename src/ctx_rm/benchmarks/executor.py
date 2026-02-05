"""TurnExecutor: build multi-turn prompt sequences with needle and noise injection."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from ctx_rm.benchmarks.models import Task

# Rough token estimate — matches runner.py:40
CHARS_PER_TOKEN = 4

NOISE_WORDS = [
    "DEBUG",
    "INFO",
    "processing",
    "request",
    "handler",
    "module",
    "function",
    "return",
    "value",
    "error",
    "status",
    "ok",
    "complete",
    "loading",
    "initialized",
    "connection",
    "timeout",
    "retry",
    "cache",
]


def generate_noise(size_tokens: int, description: str = "") -> str:
    """Generate synthetic noise text of approximately *size_tokens* tokens.

    The output has ``size_tokens * CHARS_PER_TOKEN`` characters, built by
    cycling through :data:`NOISE_WORDS` (10 words per line).

    Args:
        size_tokens: Target token count.
        description: Optional header line describing the noise block.
    """
    target_chars = size_tokens * CHARS_PER_TOKEN
    header = f"--- {description} ---\n" if description else ""
    parts: list[str] = [header]
    current_len = len(header)

    word_cycle = itertools.cycle(NOISE_WORDS)
    while current_len < target_chars:
        line = " ".join(next(word_cycle) for _ in range(10)) + "\n"
        parts.append(line)
        current_len += len(line)

    return "".join(parts)[:target_chars]


@dataclass
class TurnContent:
    """A single turn in the benchmark sequence."""

    turn_number: int
    prompt: str


class TurnExecutor:
    """Build turn sequences for a benchmark task.

    Iterates 1..min_turns, injecting needle content and noise at the
    turns specified in the task definition, and always appending a base
    prompt derived from the task scenario.
    """

    def build_turns(self, task: Task) -> list[TurnContent]:
        """Produce the full list of turns for *task*.

        Returns:
            Ordered list of :class:`TurnContent`, one per turn.
        """
        turns: list[TurnContent] = []
        base_prompt = f"Continue working on: {task.scenario.strip()}"

        for turn_num in range(1, task.min_turns + 1):
            content_parts: list[str] = []

            # Needle injections at this turn
            for needle in task.needles:
                if needle.injection_turn == turn_num:
                    content_parts.append(
                        f"[{needle.injection_method}] {needle.content}"
                    )

            # Context (noise) injections at this turn
            for injection in task.context_injections:
                if injection.turn == turn_num:
                    content_parts.append(
                        generate_noise(injection.size_tokens, injection.description)
                    )

            # Base prompt always present
            content_parts.append(base_prompt)

            turns.append(
                TurnContent(
                    turn_number=turn_num,
                    prompt="\n\n".join(content_parts),
                )
            )

        return turns
