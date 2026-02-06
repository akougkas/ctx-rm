"""Tests for the agent tool definitions and executor."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ctx_rm.agents.tools import TOOL_DEFINITIONS, ToolExecutor


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    """Create a temp working directory with sample files."""
    (tmp_path / "hello.py").write_text("print('hello world')\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("nested content\n")
    return tmp_path


@pytest.fixture()
def executor(work_dir: Path) -> ToolExecutor:
    return ToolExecutor(working_dir=str(work_dir))


# ── Tool definitions ─────────────────────────────────────────────────────────


def test_tool_definitions_is_list() -> None:
    assert isinstance(TOOL_DEFINITIONS, list)
    assert len(TOOL_DEFINITIONS) >= 4


def test_tool_definitions_have_openai_format() -> None:
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        func = tool["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func


def test_tool_names() -> None:
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert "file_read" in names
    assert "file_write" in names
    assert "run_shell" in names
    assert "list_directory" in names


# ── Tool execution ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_read(executor, work_dir) -> None:
    result = await executor.execute("file_read", {"path": str(work_dir / "hello.py")})
    assert "print('hello world')" in result


@pytest.mark.asyncio
async def test_file_read_missing(executor) -> None:
    result = await executor.execute("file_read", {"path": "/nonexistent/file.txt"})
    assert "Error" in result or "error" in result


@pytest.mark.asyncio
async def test_file_write(executor, work_dir) -> None:
    target = str(work_dir / "output.txt")
    result = await executor.execute("file_write", {"path": target, "content": "new content"})
    assert "wrote" in result.lower() or "success" in result.lower()
    assert Path(target).read_text() == "new content"


@pytest.mark.asyncio
async def test_file_write_rejects_outside_workdir(executor) -> None:
    result = await executor.execute("file_write", {"path": "/etc/passwd", "content": "bad"})
    assert "Error" in result or "denied" in result.lower() or "outside" in result.lower()


@pytest.mark.asyncio
async def test_run_shell(executor) -> None:
    result = await executor.execute("run_shell", {"command": "echo hello"})
    assert "hello" in result


@pytest.mark.asyncio
async def test_run_shell_timeout(executor) -> None:
    result = await executor.execute("run_shell", {"command": "sleep 100", "timeout": 1})
    assert "timed out" in result.lower() or "timeout" in result.lower()


@pytest.mark.asyncio
async def test_list_directory(executor, work_dir) -> None:
    result = await executor.execute("list_directory", {"path": str(work_dir)})
    assert "hello.py" in result
    assert "sub" in result


@pytest.mark.asyncio
async def test_list_directory_missing(executor) -> None:
    result = await executor.execute("list_directory", {"path": "/nonexistent/dir"})
    assert "Error" in result or "error" in result


@pytest.mark.asyncio
async def test_unknown_tool(executor) -> None:
    result = await executor.execute("nonexistent_tool", {})
    assert "unknown" in result.lower()
