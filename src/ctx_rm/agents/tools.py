"""Tool definitions and executor for the ctx-rm custom agent.

Tools are defined in OpenAI function calling format for compatibility
with llama-server's /v1/chat/completions API. The ToolExecutor handles
execution with sandboxing (working directory confinement).

Resource limits are enforced uniformly via module-level constants:

- MAX_FILE_READ_BYTES: read() is short-circuited via stat() when the file
  is larger than this, preventing OOM on huge artifacts.
- MAX_OUTPUT_CHARS: tool result strings are truncated to this length.
- DEFAULT_SHELL_TIMEOUT_SECONDS / MAX_SHELL_TIMEOUT_SECONDS: the shell
  tool timeout is bounded so an agent cannot disable timeouts by passing
  a huge value.
- GREP_TIMEOUT_SECONDS: grep has its own tighter cap.

Workdir confinement uses Path.resolve() (which follows symlinks) so a
symlink pointing outside the working directory is rejected even when the
symlink itself lives inside.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()

MAX_FILE_READ_BYTES = 2_000_000  # 2 MB cap before reading into memory
MAX_OUTPUT_CHARS = 50_000
DEFAULT_SHELL_TIMEOUT_SECONDS = 30
MAX_SHELL_TIMEOUT_SECONDS = 120
GREP_TIMEOUT_SECONDS = 15
MAX_LIST_DIRECTORY_ENTRIES = 500


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} chars total]"


_DEFAULT_INCLUDES = [
    "*.py",
    "*.js",
    "*.ts",
    "*.yaml",
    "*.yml",
    "*.json",
    "*.txt",
    "*.md",
    "*.toml",
    "*.cfg",
]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal task completion with a structured result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief description of what was accomplished.",
                    },
                    "files_changed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files created or modified.",
                    },
                },
                "required": ["summary"],
            },
        },
    },
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
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based line number to start reading from.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-based line number to stop reading at, inclusive.",
                    },
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
                        "description": (
                            "File path to write to (must be within the "
                            "working directory)."
                        ),
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
                    "cwd": {
                        "type": "string",
                        "description": "Working directory override for the command.",
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
                    "include": {
                        "type": "string",
                        "description": "Glob pattern for file types, e.g. '*.py'.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matching lines to return.",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Number of context lines before and after each match.",
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
            "done": self._done,
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

    async def _done(self, args: dict[str, Any]) -> str:
        """Signal task completion with structured result."""
        payload = {
            "status": "done",
            "summary": args["summary"],
            "files_changed": args.get("files_changed", []),
        }
        return orjson.dumps(payload).decode()

    def _resolve_path(self, path_str: str) -> Path:
        """Resolve a path relative to working_dir.

        Uses Path.resolve() which follows symlinks, so any downstream
        _check_within_workdir call sees the real target on disk. Callers
        that want to allow reads outside the workdir must opt in explicitly.
        """
        p = Path(path_str)
        if not p.is_absolute():
            p = self.working_dir / p
        return p.resolve()

    def _check_within_workdir(self, resolved: Path) -> bool:
        """Check that a resolved path is within the working directory.

        The resolved path is the real filesystem target (symlinks followed),
        so a symlink that points outside the workdir is rejected even when
        the link itself lives inside.
        """
        try:
            resolved.relative_to(self.working_dir)
            return True
        except ValueError:
            return False

    async def _file_read(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(args["path"])
        if not self._check_within_workdir(path):
            return f"Error: read denied — path outside working directory: {path}"
        if not path.exists():
            return f"Error: file not found: {path}"
        if not path.is_file():
            return f"Error: not a file: {path}"
        try:
            size = path.stat().st_size
        except OSError as exc:
            return f"Error: cannot stat {path}: {exc}"
        if size > MAX_FILE_READ_BYTES:
            return (
                f"Error: file too large to read: {path} "
                f"({size} bytes > {MAX_FILE_READ_BYTES} byte cap). "
                "Use run_shell with head/tail or grep_search for slices."
            )
        content = path.read_text(errors="replace")
        # Truncate very large files
        if len(content) > MAX_OUTPUT_CHARS:
            content = _truncate(content)

        start_line = args.get("start_line")
        end_line = args.get("end_line")

        # If no range params, return raw content (backward compatible)
        if start_line is None and end_line is None:
            return content

        # Range requested — add line numbers
        all_lines = content.split("\n")
        total = len(all_lines)

        # Clamp values
        s = max(1, start_line) if start_line is not None else 1
        e = min(total, end_line) if end_line is not None else total

        if s > total:
            return ""  # Out of range — empty result

        if s > e:
            return ""  # Invalid range — empty result

        selected = all_lines[s - 1 : e]
        numbered = [f"{s + i}: {line}" for i, line in enumerate(selected)]
        return "\n".join(numbered)

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
        return (
            f"Patched {path.name}: replaced 1 occurrence ({len(old_text)} → {len(new_text)} chars)"
        )

    async def _run_shell(self, args: dict[str, Any]) -> str:
        command = args["command"]
        requested_timeout = int(args.get("timeout", DEFAULT_SHELL_TIMEOUT_SECONDS))
        # Bound the timeout so an agent cannot request an unbounded wait.
        timeout = max(1, min(MAX_SHELL_TIMEOUT_SECONDS, requested_timeout))

        # Resolve cwd: use override if provided, else working_dir. The override
        # is still confined to the workdir so shell commands cannot climb out
        # of the sandbox via a crafted cwd argument.
        cwd_str = args.get("cwd")
        if cwd_str:
            cwd = Path(cwd_str).resolve()
            if not self._check_within_workdir(cwd):
                return f"Error: cwd denied — outside working directory: {cwd}"
        else:
            cwd = self.working_dir

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            with suppress(Exception):
                await proc.wait()
            return f"Error: command timed out after {timeout}s"

        result = stdout.decode(errors="replace")
        if stderr:
            err = stderr.decode(errors="replace")
            if err.strip():
                result += f"\nSTDERR:\n{err}"
        # Always include exit_code for consistent parsing
        result += f"\n[exit_code: {proc.returncode}]"
        return _truncate(result)

    async def _list_directory(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(args["path"])
        if not self._check_within_workdir(path):
            return f"Error: listing denied — path outside working directory: {path}"
        if not path.exists():
            return f"Error: directory not found: {path}"
        if not path.is_dir():
            return f"Error: not a directory: {path}"
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        lines: list[str] = []
        for entry in entries[:MAX_LIST_DIRECTORY_ENTRIES]:
            prefix = "d " if entry.is_dir() else "f "
            lines.append(f"{prefix}{entry.name}")
        result = "\n".join(lines)
        if len(entries) > MAX_LIST_DIRECTORY_ENTRIES:
            result += (
                f"\n... [{len(entries)} entries total, showing first {MAX_LIST_DIRECTORY_ENTRIES}]"
            )
        return result

    async def _grep_search(self, args: dict[str, Any]) -> str:
        pattern = args["pattern"]
        path = self._resolve_path(args["path"])
        if not self._check_within_workdir(path):
            return f"Error: grep denied — path outside working directory: {path}"
        if not path.exists():
            return f"Error: path not found: {path}"

        # Build grep arguments
        grep_args = ["grep", "-rn"]

        # Include filter: explicit or default list
        include = args.get("include")
        if include:
            grep_args.append(f"--include={include}")
        else:
            for ext in _DEFAULT_INCLUDES:
                grep_args.append(f"--include={ext}")

        # Context lines
        context_lines = args.get("context_lines")
        if context_lines is not None:
            grep_args.extend(["-C", str(int(context_lines))])

        grep_args.extend(["-E", pattern, str(path)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *grep_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=GREP_TIMEOUT_SECONDS)
        except TimeoutError:
            with suppress(Exception):
                proc.kill()
                await proc.wait()
            return f"Error: grep search timed out after {GREP_TIMEOUT_SECONDS}s"

        result = stdout.decode(errors="replace")
        if not result:
            return f"No matches found for pattern '{pattern}' in {path}"

        # Truncate to max_results if specified
        max_results = args.get("max_results")
        if max_results is not None:
            lines = result.split("\n")
            match_count = 0
            kept: list[str] = []
            for line in lines:
                if not line:
                    continue
                # Separator lines from -C context (--) are not matches
                if line == "--":
                    kept.append(line)
                    continue
                match_count += 1
                if match_count <= max_results:
                    kept.append(line)
                else:
                    kept.append(f"... [truncated to {max_results} results]")
                    break
            result = "\n".join(kept)

        return _truncate(result)
