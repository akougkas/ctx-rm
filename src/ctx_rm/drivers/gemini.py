"""Gemini CLI driver — subprocess-based headless integration.

Drives Gemini CLI via `gemini -p <prompt> --output-format json`.

Key Gemini CLI features used:
  - `-p` / `--prompt`: Non-interactive mode
  - `--output-format json`: Structured JSON response with stats
  - `--output-format stream-json`: Real-time JSONL event stream
  - `--yolo`: Auto-approve all tool calls
  - `-m`: Model selection (gemini-2.5-pro, gemini-2.5-flash, etc.)
  - `--resume`: Session continuity

Ref: https://github.com/google-gemini/gemini-cli
"""

from __future__ import annotations

import asyncio
import random
import shutil

import orjson
import structlog

from ctx_rm.drivers.base import AgentDriver, AgentResponse

logger = structlog.get_logger()

# Patterns in stderr/error output that indicate transient rate-limit errors
_RETRYABLE_PATTERNS = ("429", "RESOURCE_EXHAUSTED", "rate")


class GeminiCLIDriver(AgentDriver):
    """Drive Gemini CLI in headless mode via subprocess."""

    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        yolo: bool = True,
        extra_args: list[str] | None = None,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.yolo = yolo
        self.extra_args = extra_args or []
        self.max_retries = max_retries

    @property
    def name(self) -> str:
        return "gemini-cli"

    async def invoke(
        self,
        prompt: str,
        context: str | None = None,
        working_dir: str | None = None,
        timeout: int = 300,
    ) -> AgentResponse:
        """Invoke Gemini CLI with a prompt and optional context.

        Transient errors (429, RESOURCE_EXHAUSTED, rate-limit) are retried
        with exponential backoff + jitter up to ``max_retries`` times.
        """
        full_prompt = self._build_prompt(prompt, context)

        cmd = [
            "gemini",
            "-p", full_prompt,
            "--output-format", "json",
            "-m", self.model,
        ]
        if self.yolo:
            cmd.append("--yolo")
        cmd.extend(self.extra_args)

        logger.debug("gemini_invoke", model=self.model, prompt_len=len(full_prompt))

        for attempt in range(self.max_retries + 1):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except TimeoutError:
                logger.error("gemini_timeout", timeout=timeout)
                return AgentResponse(
                    text="", success=False, error=f"Timeout after {timeout}s"
                )
            except FileNotFoundError:
                return AgentResponse(
                    text="",
                    success=False,
                    error="gemini CLI not found. Install with: npm install -g @google/gemini-cli",
                )

            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()

                # Check if this is a retryable transient error
                if attempt < self.max_retries and self._is_retryable(err):
                    delay = (2**attempt) + random.uniform(0, 1)
                    logger.warning(
                        "gemini_retry",
                        attempt=attempt + 1,
                        max_retries=self.max_retries,
                        delay=round(delay, 2),
                        error=err[:200],
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error(
                    "gemini_error", returncode=proc.returncode, stderr=err[:500]
                )
                return AgentResponse(
                    text="",
                    success=False,
                    error=f"Exit code {proc.returncode}: {err[:500]}",
                )

            return self._parse_json_output(stdout)

        # Should not reach here, but satisfy type checker
        return AgentResponse(text="", success=False, error="Max retries exhausted")  # pragma: no cover

    @staticmethod
    def _is_retryable(error_text: str) -> bool:
        """Check whether an error message indicates a transient rate-limit issue."""
        lower = error_text.lower()
        return any(pat.lower() in lower for pat in _RETRYABLE_PATTERNS)

    async def check_available(self) -> bool:
        """Check if gemini CLI is installed."""
        return shutil.which("gemini") is not None

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
        """Parse Gemini CLI's JSON output format.

        Expected format:
        {
          "response": "...",
          "stats": {
            "models": { "gemini-2.5-pro": { "tokens": {...} } },
            "tools": { "totalCalls": N, "totalSuccess": N },
            "files": { "totalLinesAdded": N, "totalLinesRemoved": N }
          }
        }
        """
        try:
            data = orjson.loads(stdout)
        except orjson.JSONDecodeError:
            # Fallback: treat as plain text
            text = stdout.decode(errors="replace").strip()
            return AgentResponse(text=text, raw_json={})

        response_text = data.get("response", "")
        stats = data.get("stats", {})

        # Extract token usage from stats
        prompt_tokens = 0
        completion_tokens = 0
        models = stats.get("models", {})
        for model_stats in models.values():
            tokens = model_stats.get("tokens", {})
            prompt_tokens += tokens.get("input", 0) or tokens.get("inputTokens", 0)
            completion_tokens += tokens.get("candidates", 0) or tokens.get("outputTokens", 0)

        # Extract tool usage
        tool_stats = stats.get("tools", {})
        tool_calls = tool_stats.get("totalCalls", 0)

        # Extract file changes
        file_stats = stats.get("files", {})
        files_modified = []
        if file_stats.get("totalLinesAdded", 0) > 0 or file_stats.get("totalLinesRemoved", 0) > 0:
            files_modified = file_stats.get("changedFiles", [])

        return AgentResponse(
            text=response_text,
            raw_json=data,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            tool_calls=tool_calls,
            files_modified=files_modified,
            success=True,
        )
