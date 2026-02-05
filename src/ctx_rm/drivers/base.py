"""Base protocol for CLI agent drivers.

Drivers wrap CLI agents (Gemini CLI, Claude Code) in headless/print mode,
driving them via subprocess. Each driver:
  1. Accepts a prompt + context segments
  2. Invokes the CLI in non-interactive mode (-p / --output-format json)
  3. Parses the structured output
  4. Returns a response with token usage metadata

The key insight: we don't manipulate the agent's internal context.
Instead, we construct the prompt for each turn, incorporating only the
segments that ctx-rm's ContextBus considers active.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResponse:
    """Parsed response from a CLI agent invocation."""

    text: str
    raw_json: dict[str, Any] = field(default_factory=dict)

    # Token usage (from the agent's own reporting)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Tool use tracking
    tool_calls: int = 0
    tools_used: list[str] = field(default_factory=list)

    # Files modified (for benchmark evaluation)
    files_modified: list[str] = field(default_factory=list)

    # Timing
    elapsed_ms: int = 0

    # Whether the agent completed or hit a limit
    success: bool = True
    error: str | None = None


class AgentDriver(ABC):
    """Abstract base for CLI agent drivers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Driver identifier."""

    @abstractmethod
    async def invoke(
        self,
        prompt: str,
        context: str | None = None,
        working_dir: str | None = None,
        timeout: int = 300,
    ) -> AgentResponse:
        """Invoke the CLI agent with a prompt.

        Args:
            prompt: The task/query for this turn.
            context: Additional context to prepend (rendered active segments).
            working_dir: Directory to run the agent in.
            timeout: Max seconds to wait.

        Returns:
            Parsed response with text and metadata.
        """

    @abstractmethod
    async def check_available(self) -> bool:
        """Check if the CLI tool is installed and accessible."""
