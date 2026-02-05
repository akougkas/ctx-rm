"""Claude Code driver — subprocess-based headless integration.

Drives Claude Code via `claude -p <prompt> --output-format json`.

Key Claude Code features used:
  - `-p` / `--print`: Non-interactive (SDK/print) mode
  - `--output-format json`: Structured JSON response
  - `--output-format stream-json`: Real-time JSONL event stream
  - `--dangerously-skip-permissions`: Auto-approve all actions
  - `--model`: Model selection (sonnet, opus)
  - `--max-turns`: Limit agentic turns
  - `--continue` / `--resume`: Session continuity
  - `--append-system-prompt`: Inject additional context/instructions
  - `--session-id`: Use specific session ID

Ref: https://code.claude.com/docs/en/cli-reference
"""

from __future__ import annotations

import asyncio
import shutil

import orjson
import structlog

from ctx_rm.drivers.base import AgentDriver, AgentResponse

logger = structlog.get_logger()


class ClaudeCodeDriver(AgentDriver):
    """Drive Claude Code in headless/print mode via subprocess."""

    def __init__(
        self,
        model: str = "sonnet",
        skip_permissions: bool = True,
        max_turns: int | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self.model = model
        self.skip_permissions = skip_permissions
        self.max_turns = max_turns
        self.extra_args = extra_args or []

    @property
    def name(self) -> str:
        return "claude-code"

    async def invoke(
        self,
        prompt: str,
        context: str | None = None,
        working_dir: str | None = None,
        timeout: int = 300,
    ) -> AgentResponse:
        """Invoke Claude Code with a prompt and optional context."""
        full_prompt = self._build_prompt(prompt, context)

        cmd = [
            "claude",
            "-p", full_prompt,
            "--output-format", "json",
            "--model", self.model,
        ]

        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        if self.max_turns is not None:
            cmd.extend(["--max-turns", str(self.max_turns)])

        cmd.extend(self.extra_args)

        logger.debug("claude_invoke", model=self.model, prompt_len=len(full_prompt))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.error("claude_timeout", timeout=timeout)
            return AgentResponse(
                text="", success=False, error=f"Timeout after {timeout}s"
            )
        except FileNotFoundError:
            return AgentResponse(
                text="",
                success=False,
                error="claude not found. Install: npm install -g @anthropic-ai/claude-code",
            )

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            logger.error("claude_error", returncode=proc.returncode, stderr=err[:500])
            return AgentResponse(
                text="", success=False, error=f"Exit code {proc.returncode}: {err[:500]}"
            )

        return self._parse_json_output(stdout)

    async def check_available(self) -> bool:
        """Check if claude CLI is installed."""
        return shutil.which("claude") is not None

    # ── Internal ────────────────────────────────────────────────────────

    def _build_prompt(self, prompt: str, context: str | None) -> str:
        """Construct the full prompt with context prefix."""
        if not context:
            return prompt

        return (
            f"<context>\n{context}\n</context>\n\n"
            f"<task>\n{prompt}\n</task>"
        )

    def _parse_json_output(self, stdout: bytes) -> AgentResponse:
        """Parse Claude Code's JSON output format.

        Claude Code -p --output-format json returns:
        {
          "type": "result",
          "subtype": "success",
          "cost_usd": 0.123,
          "is_error": false,
          "duration_ms": 12345,
          "duration_api_ms": 10000,
          "num_turns": 5,
          "result": "...",
          "session_id": "uuid",
          "total_cost_usd": 0.123
        }
        """
        try:
            data = orjson.loads(stdout)
        except orjson.JSONDecodeError:
            # Fallback: treat as plain text
            text = stdout.decode(errors="replace").strip()
            return AgentResponse(text=text, raw_json={})

        response_text = data.get("result", "")
        is_error = data.get("is_error", False)
        duration_ms = data.get("duration_ms", 0)
        num_turns = data.get("num_turns", 0)

        return AgentResponse(
            text=response_text,
            raw_json=data,
            tool_calls=num_turns,
            elapsed_ms=duration_ms,
            success=not is_error,
            error=response_text if is_error else None,
        )
