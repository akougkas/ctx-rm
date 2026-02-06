"""Tests for CLI bench --all and compare with nested results."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest
from typer.testing import CliRunner

from ctx_rm.cli.main import app

runner = CliRunner()


# ── Sample data helpers ──────────────────────────────────────────────────────


def _write_metrics(path: Path, tokens_in: int = 500, tokens_evicted: int = 100) -> None:
    data = {
        "summary": {
            "total_ingested_tokens": tokens_in,
            "total_evicted_tokens": tokens_evicted,
            "peak_utilization": 0.75,
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(data))


def _write_evaluation(path: Path, all_passed: bool = True, summary: str = "2/2 checks passed") -> None:
    data = {
        "task_id": path.parent.parent.parent.name,
        "all_passed": all_passed,
        "summary": summary,
        "checks": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(data))


# ── bench tests ──────────────────────────────────────────────────────────────


@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_driver_is_option_not_positional(mock_runner_cls: MagicMock) -> None:
    """--driver is an option, not a positional argument."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    result = runner.invoke(app, ["bench", "--driver", "gemini", "--task", "CR-001", "--mode", "ctx-rm"])
    assert result.exit_code == 0, result.output
    mock_runner_cls.assert_called_once()
    call_kwargs = mock_runner_cls.call_args.kwargs
    assert call_kwargs["driver_name"] == "gemini"


@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_single_run_no_working_dir(mock_runner_cls: MagicMock) -> None:
    """Single-run bench does not pass working_dir to BenchmarkRunner."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    result = runner.invoke(app, ["bench", "--task", "CR-001"])
    assert result.exit_code == 0, result.output
    call_kwargs = mock_runner_cls.call_args.kwargs
    assert "working_dir" not in call_kwargs


@patch("ctx_rm.drivers.gemini.GeminiCLIDriver.check_available", new_callable=AsyncMock, return_value=True)
@patch("ctx_rm.drivers.claude.ClaudeCodeDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.benchmarks.loader.TaskLoader.list_task_ids", return_value=["CR-001", "CR-002"])
@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_all_flag_iterates_combinations(
    mock_runner_cls: MagicMock,
    _mock_loader: MagicMock,
    _mock_claude: AsyncMock,
    _mock_gemini: AsyncMock,
) -> None:
    """--all iterates all tasks x 3 modes x available drivers."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    result = runner.invoke(app, ["bench", "--all"])
    assert result.exit_code == 0, result.output
    # 2 tasks x 3 modes x 1 driver = 6 calls
    assert mock_runner_cls.call_count == 6
    assert "Batch complete" in result.output
    assert "6/6" in result.output


@patch("ctx_rm.drivers.gemini.GeminiCLIDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.drivers.claude.ClaudeCodeDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.benchmarks.loader.TaskLoader.list_task_ids", return_value=["CR-001"])
@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_all_skips_unavailable_drivers(
    mock_runner_cls: MagicMock,
    _mock_loader: MagicMock,
    _mock_claude: AsyncMock,
    _mock_gemini: AsyncMock,
) -> None:
    """--all with no available drivers prints error, never calls BenchmarkRunner."""
    result = runner.invoke(app, ["bench", "--all"])
    assert result.exit_code == 0, result.output
    assert mock_runner_cls.call_count == 0
    assert "No drivers available" in result.output


# ── compare tests ────────────────────────────────────────────────────────────


def test_compare_reads_nested_dirs(tmp_path: Path) -> None:
    """compare walks results/{task}/{mode}/{driver}/ and shows data."""
    leaf = tmp_path / "CR-001" / "ctx-rm" / "gemini"
    _write_metrics(leaf / "metrics.json")
    _write_evaluation(leaf / "evaluation.json", all_passed=True, summary="2/2 checks passed")

    result = runner.invoke(app, ["compare", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "CR-001" in result.output
    assert "ctx-rm" in result.output
    assert "gemini" in result.output
    assert "PASS" in result.output


def test_compare_shows_mode_summary(tmp_path: Path) -> None:
    """compare prints mode-aggregated summary lines."""
    for task_id in ["CR-001", "CR-002"]:
        for mode_name in ["minimal", "ctx-rm"]:
            leaf = tmp_path / task_id / mode_name / "gemini"
            _write_metrics(leaf / "metrics.json")
            passed = mode_name == "ctx-rm"
            _write_evaluation(
                leaf / "evaluation.json",
                all_passed=passed,
                summary="2/2" if passed else "1/2",
            )

    result = runner.invoke(app, ["compare", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Mode Summary" in result.output
    # ctx-rm: 2/2 passed, minimal: 0/2 passed
    assert "ctx-rm" in result.output
    assert "minimal" in result.output


def test_compare_handles_missing_evaluation(tmp_path: Path) -> None:
    """compare does not crash when evaluation.json is missing; shows N/A."""
    leaf = tmp_path / "CR-001" / "full" / "gemini"
    _write_metrics(leaf / "metrics.json")
    # No evaluation.json written

    result = runner.invoke(app, ["compare", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "CR-001" in result.output
    assert "N/A" in result.output
