"""Tests for tool upgrades: done, file_read ranges, grep_search filters, run_shell exit_code+cwd."""

from __future__ import annotations

import pytest

from ctx_rm.agents.tools import TOOL_DEFINITIONS, ToolExecutor


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_10_line_file(tmp_path):
    """Create a 10-line file and return its path."""
    p = tmp_path / "lines.txt"
    p.write_text("\n".join(f"line {i}" for i in range(1, 11)))
    return p


def _tool_names() -> list[str]:
    return [t["function"]["name"] for t in TOOL_DEFINITIONS]


def _tool_def(name: str) -> dict:
    for t in TOOL_DEFINITIONS:
        if t["function"]["name"] == name:
            return t["function"]
    raise KeyError(f"No tool definition named {name}")


# ── TOOL-01: done tool ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_done_tool_returns_structured_result(tmp_path) -> None:
    """Calling done returns JSON with status, summary, files_changed."""
    import json

    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "done", {"summary": "Fixed bug", "files_changed": ["a.py"]}
    )
    parsed = json.loads(result)
    assert parsed["status"] == "done"
    assert parsed["summary"] == "Fixed bug"
    assert parsed["files_changed"] == ["a.py"]


@pytest.mark.asyncio
async def test_done_tool_in_definitions() -> None:
    """TOOL_DEFINITIONS contains done with required summary and optional files_changed."""
    assert "done" in _tool_names()
    defn = _tool_def("done")
    props = defn["parameters"]["properties"]
    assert "summary" in props
    assert props["summary"]["type"] == "string"
    assert "files_changed" in props
    assert props["files_changed"]["type"] == "array"
    assert "summary" in defn["parameters"]["required"]
    # files_changed is optional
    assert "files_changed" not in defn["parameters"].get("required", [])


# ── TOOL-02: file_read line ranges ──────────────────────────────────────


@pytest.mark.asyncio
async def test_file_read_full(tmp_path) -> None:
    """Full read (no range params) returns raw content WITHOUT line numbers."""
    p = _make_10_line_file(tmp_path)
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute("file_read", {"path": str(p)})
    # Must contain raw content without line number prefixes
    assert result.startswith("line 1\n")
    assert "1: line 1" not in result


@pytest.mark.asyncio
async def test_file_read_with_range(tmp_path) -> None:
    """Reading lines 3-5 returns exactly 3 numbered lines."""
    p = _make_10_line_file(tmp_path)
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "file_read", {"path": str(p), "start_line": 3, "end_line": 5}
    )
    lines = result.strip().split("\n")
    assert len(lines) == 3
    assert lines[0] == "3: line 3"
    assert lines[1] == "4: line 4"
    assert lines[2] == "5: line 5"


@pytest.mark.asyncio
async def test_file_read_start_only(tmp_path) -> None:
    """start_line=8 returns lines 8-10 with line number prefixes."""
    p = _make_10_line_file(tmp_path)
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "file_read", {"path": str(p), "start_line": 8}
    )
    lines = result.strip().split("\n")
    assert len(lines) == 3
    assert lines[0] == "8: line 8"
    assert lines[2] == "10: line 10"


@pytest.mark.asyncio
async def test_file_read_end_only(tmp_path) -> None:
    """end_line=3 returns lines 1-3 with line number prefixes."""
    p = _make_10_line_file(tmp_path)
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "file_read", {"path": str(p), "end_line": 3}
    )
    lines = result.strip().split("\n")
    assert len(lines) == 3
    assert lines[0] == "1: line 1"
    assert lines[2] == "3: line 3"


@pytest.mark.asyncio
async def test_file_read_out_of_range(tmp_path) -> None:
    """start_line=100 on a 10-line file returns empty or informative result."""
    p = _make_10_line_file(tmp_path)
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "file_read", {"path": str(p), "start_line": 100}
    )
    # Should not error, should be empty or informative
    assert "Error" not in result
    assert result.strip() == "" or "no lines" in result.lower()


# ── TOOL-03: grep_search filters ────────────────────────────────────────


@pytest.mark.asyncio
async def test_grep_with_include_filter(tmp_path) -> None:
    """include='*.py' filters to only .py files."""
    (tmp_path / "a.py").write_text("hello world")
    (tmp_path / "b.txt").write_text("hello world")
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "grep_search", {"pattern": "hello", "path": str(tmp_path), "include": "*.py"}
    )
    assert "a.py" in result
    assert "b.txt" not in result


@pytest.mark.asyncio
async def test_grep_with_max_results(tmp_path) -> None:
    """max_results=3 limits output to at most 3 match lines."""
    # Create a file with many matching lines
    content = "\n".join(f"match line {i}" for i in range(20))
    (tmp_path / "many.py").write_text(content)
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "grep_search",
        {"pattern": "match", "path": str(tmp_path), "max_results": 3},
    )
    # Count actual match lines (not separator lines like --)
    match_lines = [
        ln for ln in result.strip().split("\n")
        if ln and not ln.startswith("--") and "truncated" not in ln
    ]
    assert len(match_lines) <= 3
    assert "truncated" in result.lower()


@pytest.mark.asyncio
async def test_grep_with_context_lines(tmp_path) -> None:
    """context_lines=2 passes -C 2 to grep."""
    lines = ["aaa", "bbb", "TARGET", "ccc", "ddd"]
    (tmp_path / "ctx.py").write_text("\n".join(lines))
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "grep_search",
        {"pattern": "TARGET", "path": str(tmp_path), "context_lines": 2},
    )
    # With -C 2, we should see bbb and ccc around TARGET
    assert "bbb" in result
    assert "TARGET" in result
    assert "ccc" in result


# ── TOOL-04: run_shell exit code + cwd ──────────────────────────────────


@pytest.mark.asyncio
async def test_run_shell_exit_code_success(tmp_path) -> None:
    """exit_code: 0 is always present in output for successful commands."""
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute("run_shell", {"command": "echo hello"})
    assert "hello" in result
    assert "[exit_code: 0]" in result


@pytest.mark.asyncio
async def test_run_shell_exit_code_failure(tmp_path) -> None:
    """exit_code is 42 for a command that exits with 42."""
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute("run_shell", {"command": "exit 42"})
    assert "[exit_code: 42]" in result


@pytest.mark.asyncio
async def test_run_shell_cwd_override(tmp_path) -> None:
    """cwd override changes the working directory for the command."""
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "marker.txt").write_text("here")
    executor = ToolExecutor(working_dir=str(tmp_path))
    result = await executor.execute(
        "run_shell", {"command": "ls", "cwd": str(subdir)}
    )
    assert "marker.txt" in result
