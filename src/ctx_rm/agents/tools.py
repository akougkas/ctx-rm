"""Tool definitions and executor for the ctx-rm custom agent.

Tools are defined in OpenAI function calling format for compatibility
with llama-server's /v1/chat/completions API. The ToolExecutor handles
execution with sandboxing (working directory confinement).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path to read.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file. Creates parent directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to write to (must be within the working directory).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command and return stdout + stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30).",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search for a pattern in files under a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search in.",
                    },
                },
                "required": ["pattern", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_patch",
            "description": (
                "Apply a targeted search-and-replace edit to a file. "
                "The old_text must appear exactly once in the file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to edit.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact text to find (must be unique in the file).",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
]


class ToolExecutor:
    """Execute tool calls within a sandboxed working directory."""

    def __init__(self, working_dir: str) -> None:
        self.working_dir = Path(working_dir).resolve()

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool call and return the result as a string."""
        handler = {
            "file_read": self._file_read,
            "file_write": self._file_write,
            "file_patch": self._file_patch,
            "run_shell": self._run_shell,
            "list_directory": self._list_directory,
            "grep_search": self._grep_search,
        }.get(tool_name)

        if handler is None:
            return f"Error: unknown tool '{tool_name}'"

        try:
            return await handler(arguments)
        except Exception as e:
            logger.warning("tool_error", tool=tool_name, error=str(e))
            return f"Error executing {tool_name}: {e}"

    def _resolve_path(self, path_str: str) -> Path:
        """Resolve a path relative to working_dir."""
        p = Path(path_str)
        if not p.is_absolute():
            p = self.working_dir / p
        return p.resolve()

    def _check_within_workdir(self, resolved: Path) -> bool:
        """Check that a path is within the working directory."""
        try:
            resolved.relative_to(self.working_dir)
            return True
        except ValueError:
            return False

    async def _file_read(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(args["path"])
        if not path.exists():
            return f"Error: file not found: {path}"
        if not path.is_file():
            return f"Error: not a file: {path}"
        content = path.read_text(errors="replace")
        # Truncate very large files
        if len(content) > 50_000:
            return content[:50_000] + f"\n\n... [truncated, {len(content)} chars total]"
        return content

    async def _file_write(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(args["path"])
        if not self._check_within_workdir(path):
            return f"Error: write denied — path outside working directory: {path}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"])
        return f"Wrote {len(args['content'])} chars to {path}"

    async def _file_patch(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(args["path"])
        if not self._check_within_workdir(path):
            return f"Error: patch denied — path outside working directory: {path}"
        if not path.exists():
            return f"Error: file not found: {path}"
        if not path.is_file():
            return f"Error: not a file: {path}"

        old_text = args["old_text"]
        new_text = args["new_text"]
        content = path.read_text(errors="replace")
        count = content.count(old_text)

        if count == 0:
            return f"Error: old_text not found in {path.name}"
        if count > 1:
            return f"Error: old_text is not unique in {path.name} ({count} occurrences)"

        patched = content.replace(old_text, new_text, 1)
        path.write_text(patched)
        return f"Patched {path.name}: replaced 1 occurrence ({len(old_text)} → {len(new_text)} chars)"

    async def _run_shell(self, args: dict[str, Any]) -> str:
        command = args["command"]
        timeout = int(args.get("timeout", 30))

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_dir),
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            return f"Error: command timed out after {timeout}s"

        result = stdout.decode(errors="replace")
        if stderr:
            err = stderr.decode(errors="replace")
            if err.strip():
                result += f"\nSTDERR:\n{err}"
        if proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        # Truncate long output
        if len(result) > 20_000:
            result = result[:20_000] + f"\n... [truncated, {len(result)} chars total]"
        return result

    async def _list_directory(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(args["path"])
        if not path.exists():
            return f"Error: directory not found: {path}"
        if not path.is_dir():
            return f"Error: not a directory: {path}"
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        lines = []
        for entry in entries[:200]:
            prefix = "d " if entry.is_dir() else "f "
            lines.append(f"{prefix}{entry.name}")
        result = "\n".join(lines)
        if len(entries) > 200:
            result += f"\n... [{len(entries)} entries total, showing first 200]"
        return result

    async def _grep_search(self, args: dict[str, Any]) -> str:
        pattern = args["pattern"]
        path = self._resolve_path(args["path"])
        if not path.exists():
            return f"Error: path not found: {path}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "grep", "-rn", "--include=*.py", "--include=*.js",
                "--include=*.ts", "--include=*.yaml", "--include=*.yml",
                "--include=*.json", "--include=*.txt", "--include=*.md",
                "--include=*.toml", "--include=*.cfg",
                "-E", pattern, str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        except TimeoutError:
            return "Error: grep search timed out"

        result = stdout.decode(errors="replace")
        if not result:
            return f"No matches found for pattern '{pattern}' in {path}"
        if len(result) > 20_000:
            result = result[:20_000] + "\n... [truncated]"
        return result
