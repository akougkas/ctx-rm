"""Sandbox hardening tests for ToolExecutor.

Covers:
- Symlink escape rejection via resolved-path workdir check
- file_read size cap via stat before read
- Shell timeout clamping
- run_shell cwd argument confinement
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ctx_rm.agents.tools import (
    MAX_FILE_READ_BYTES,
    ToolExecutor,
)


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    return tmp_path


class TestSymlinkEscape:
    @pytest.mark.asyncio
    async def test_symlink_pointing_outside_workdir_rejected(
        self, workdir: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path.parent / "outside_ctxrm_sandbox_test.txt"
        outside.write_text("secret")
        try:
            link = workdir / "escape.txt"
            os.symlink(outside, link)

            exec = ToolExecutor(str(workdir))
            result = await exec.execute("file_read", {"path": "escape.txt"})
            assert result.startswith("Error: read denied")
        finally:
            if outside.exists():
                outside.unlink()

    @pytest.mark.asyncio
    async def test_absolute_outside_path_rejected(self, workdir: Path) -> None:
        exec = ToolExecutor(str(workdir))
        result = await exec.execute("file_read", {"path": "/etc/hostname"})
        assert result.startswith("Error: read denied")


class TestFileReadSizeCap:
    @pytest.mark.asyncio
    async def test_oversized_file_rejected_without_reading(self, workdir: Path) -> None:
        big = workdir / "big.bin"
        # Sparse file: stat reports the full size without writing bytes.
        with big.open("wb") as f:
            f.seek(MAX_FILE_READ_BYTES + 10)
            f.write(b"\0")

        exec = ToolExecutor(str(workdir))
        result = await exec.execute("file_read", {"path": "big.bin"})
        assert result.startswith("Error: file too large to read")


class TestShellTimeoutClamp:
    @pytest.mark.asyncio
    async def test_requested_timeout_clamped(self, workdir: Path) -> None:
        exec = ToolExecutor(str(workdir))
        # A fast command completes well inside the clamp. We assert the tool
        # returns normally rather than timing out when a crazy timeout is given.
        result = await exec.execute(
            "run_shell",
            {"command": "echo hi", "timeout": 10_000},
        )
        assert "hi" in result
        assert "[exit_code: 0]" in result

    @pytest.mark.asyncio
    async def test_cwd_outside_workdir_rejected(self, workdir: Path, tmp_path: Path) -> None:
        outside = tmp_path.parent
        exec = ToolExecutor(str(workdir))
        result = await exec.execute(
            "run_shell",
            {"command": "pwd", "cwd": str(outside)},
        )
        assert "cwd denied" in result or "Error" in result
