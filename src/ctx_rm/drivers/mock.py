"""Mock agent driver for pipeline validation without external CLI tools.

Returns deterministic responses with realistic token estimates,
enabling end-to-end benchmark pipeline testing (loader -> fixtures ->
turns -> driver -> bus -> watcher -> evaluator -> results) without
requiring Gemini CLI or Claude Code to be installed.
"""

from __future__ import annotations

import structlog

from ctx_rm.drivers.base import AgentDriver, AgentResponse

logger = structlog.get_logger()


class MockDriver(AgentDriver):
    """Deterministic driver for pipeline validation and testing."""

    @property
    def name(self) -> str:
        return "mock"

    async def invoke(
        self,
        prompt: str,
        context: str | None = None,
        working_dir: str | None = None,
        timeout: int = 300,
    ) -> AgentResponse:
        """Return a deterministic response with realistic token estimates."""
        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = 10
        logger.debug(
            "mock_invoke",
            prompt_len=len(prompt),
            prompt_tokens=prompt_tokens,
        )
        return AgentResponse(
            text=(
                "Mock agent response for testing. "
                "This simulates an agent reply for benchmark pipeline validation."
            ),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            tool_calls=0,
            success=True,
            elapsed_ms=1,
        )

    async def check_available(self) -> bool:
        """Mock driver is always available."""
        return True
