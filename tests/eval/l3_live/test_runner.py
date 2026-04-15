"""Tests for the narrow L3 live runner."""

from __future__ import annotations

from typing import Any

import pytest

from ctx_rm.drivers.llamacpp import ChatResponse
from ctx_rm.eval.l3_live.runner import L3RunConfig, run_live_eval


class StubDriver:
    """Deterministic chat driver for L3 runner tests."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self._idx = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        response = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return response


@pytest.mark.asyncio
async def test_live_runner_returns_agent_result(tmp_path) -> None:
    driver = StubDriver(
        [
            ChatResponse(
                content="Task complete.",
                prompt_tokens=120,
                completion_tokens=20,
                total_tokens=140,
            )
        ]
    )
    config = L3RunConfig(
        working_dir=str(tmp_path),
        system_prompt="You are a careful coding agent.",
        task="Summarize the current directory.",
        policy_name="budget",
        token_budget=2_000,
        max_turns=2,
    )

    result = await run_live_eval(config, driver=driver)

    assert result.final_response == "Task complete."
    assert result.turns == 1
    assert result.total_prompt_tokens == 120
    assert result.total_completion_tokens == 20
    assert result.tool_calls_made == 0

