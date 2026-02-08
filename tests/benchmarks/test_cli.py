"""Tests for CLI bench --all, compare, tasks, and info commands."""

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
        "task_id": "test",
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
@patch("ctx_rm.drivers.llamacpp.LlamaCppDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.benchmarks.loader.TaskLoader.list_task_ids", return_value=["CR-001", "CR-002"])
@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_all_flag_iterates_combinations(
    mock_runner_cls: MagicMock,
    _mock_loader: MagicMock,
    _mock_llamacpp: AsyncMock,
    _mock_claude: AsyncMock,
    _mock_gemini: AsyncMock,
) -> None:
    """--all iterates all tasks x 3 modes x available drivers."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    result = runner.invoke(app, ["bench", "--all"])
    assert result.exit_code == 0, result.output
    # 2 tasks x 3 modes x 1 driver (gemini) = 6 calls
    assert mock_runner_cls.call_count == 6
    assert "Batch complete" in result.output
    assert "6/6" in result.output


@patch("ctx_rm.drivers.gemini.GeminiCLIDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.drivers.claude.ClaudeCodeDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.drivers.llamacpp.LlamaCppDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.benchmarks.loader.TaskLoader.list_task_ids", return_value=["CR-001"])
@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_all_skips_unavailable_drivers(
    mock_runner_cls: MagicMock,
    _mock_loader: MagicMock,
    _mock_llamacpp: AsyncMock,
    _mock_claude: AsyncMock,
    _mock_gemini: AsyncMock,
) -> None:
    """--all with no available drivers prints error, never calls BenchmarkRunner."""
    result = runner.invoke(app, ["bench", "--all"])
    assert result.exit_code == 0, result.output
    assert mock_runner_cls.call_count == 0
    assert "No drivers available" in result.output


@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_accepts_policy_and_scorer(mock_runner_cls: MagicMock) -> None:
    """bench accepts --policy and --scorer enum options."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    result = runner.invoke(app, [
        "bench", "--task", "CR-001", "--policy", "arc", "--scorer", "heuristic",
    ])
    assert result.exit_code == 0, result.output
    call_kwargs = mock_runner_cls.call_args.kwargs
    assert call_kwargs["policy_name"] == "arc"


@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_accepts_sequential_scorer(mock_runner_cls: MagicMock) -> None:
    """bench accepts --scorer sequential."""
    import os

    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    old_scorer = os.environ.get("CTX_RM_SCORER")
    try:
        result = runner.invoke(app, [
            "bench", "--task", "CR-001", "--scorer", "sequential",
        ])
        assert result.exit_code == 0, result.output
    finally:
        if old_scorer is None:
            os.environ.pop("CTX_RM_SCORER", None)
        else:
            os.environ["CTX_RM_SCORER"] = old_scorer


@patch("ctx_rm.benchmarks.runner.BenchmarkRunner")
def test_bench_rejects_invalid_mode(mock_runner_cls: MagicMock) -> None:
    """Invalid mode value is rejected by the enum."""
    result = runner.invoke(app, ["bench", "--mode", "invalid"])
    assert result.exit_code != 0


# ── compare tests ────────────────────────────────────────────────────────────


def _invoke_compare(tmp_path: Path) -> object:
    """Invoke compare with wide terminal to avoid Rich truncation."""
    import os
    old = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = "200"
    try:
        return runner.invoke(app, ["compare", str(tmp_path)])
    finally:
        if old is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = old


def test_compare_legacy_flat_structure(tmp_path: Path) -> None:
    """compare reads legacy flat results/{task}/{mode}/{driver}/metrics.json."""
    leaf = tmp_path / "CR-001" / "minimal" / "gemini"
    _write_metrics(leaf / "metrics.json")
    _write_evaluation(leaf / "evaluation.json", all_passed=True, summary="2/2")

    result = _invoke_compare(tmp_path)
    assert result.exit_code == 0, result.output
    assert "CR-001" in result.output
    assert "minimal" in result.output
    assert "gemini" in result.output
    # Legacy single run shows pass rate as 1/1
    assert "1/1" in result.output
    # Policy column shows "--" for non-ctx-rm
    assert "--" in result.output


def test_compare_multi_run_aggregation(tmp_path: Path) -> None:
    """compare aggregates run-N directories using median."""
    base = tmp_path / "CR-001" / "minimal" / "gemini"
    # 3 runs with different metrics
    _write_metrics(base / "run-1" / "metrics.json", tokens_in=100, tokens_evicted=10)
    _write_evaluation(base / "run-1" / "evaluation.json", all_passed=True, summary="2/2")

    _write_metrics(base / "run-2" / "metrics.json", tokens_in=200, tokens_evicted=20)
    _write_evaluation(base / "run-2" / "evaluation.json", all_passed=False, summary="1/2")

    _write_metrics(base / "run-3" / "metrics.json", tokens_in=300, tokens_evicted=30)
    _write_evaluation(base / "run-3" / "evaluation.json", all_passed=True, summary="2/2")

    result = _invoke_compare(tmp_path)
    assert result.exit_code == 0, result.output
    # Median of 100,200,300 = 200
    assert "200" in result.output
    # Pass rate: 2 passed out of 3
    assert "2/3" in result.output
    # Runs column: 3/3
    assert "3/3" in result.output


def test_compare_ctx_rm_policy_subdirs(tmp_path: Path) -> None:
    """compare handles ctx-rm/{driver}/{policy}/run-N/ structure."""
    base = tmp_path / "CR-001" / "ctx-rm" / "gemini" / "budget"
    _write_metrics(base / "run-1" / "metrics.json", tokens_in=500, tokens_evicted=100)
    _write_evaluation(base / "run-1" / "evaluation.json", all_passed=True, summary="2/2")

    _write_metrics(base / "run-2" / "metrics.json", tokens_in=600, tokens_evicted=200)
    _write_evaluation(base / "run-2" / "evaluation.json", all_passed=True, summary="2/2")

    result = _invoke_compare(tmp_path)
    assert result.exit_code == 0, result.output
    assert "ctx-rm" in result.output
    assert "budget" in result.output
    assert "2/2" in result.output  # pass rate: both passed


def test_compare_multiple_policies(tmp_path: Path) -> None:
    """compare shows separate rows for different policies."""
    for pol in ["lru", "arc"]:
        base = tmp_path / "CR-001" / "ctx-rm" / "gemini" / pol
        _write_metrics(base / "run-1" / "metrics.json", tokens_in=500)
        _write_evaluation(base / "run-1" / "evaluation.json", all_passed=True, summary="2/2")

    result = _invoke_compare(tmp_path)
    assert result.exit_code == 0, result.output
    assert "lru" in result.output
    assert "arc" in result.output


def test_compare_shows_mode_summary(tmp_path: Path) -> None:
    """compare prints mode-aggregated summary lines."""
    for task_id in ["CR-001", "CR-002"]:
        for mode_name in ["minimal", "ctx-rm"]:
            if mode_name == "ctx-rm":
                leaf = tmp_path / task_id / mode_name / "gemini" / "budget"
            else:
                leaf = tmp_path / task_id / mode_name / "gemini"
            _write_metrics(leaf / "run-1" / "metrics.json")
            passed = mode_name == "ctx-rm"
            _write_evaluation(
                leaf / "run-1" / "evaluation.json",
                all_passed=passed,
                summary="2/2" if passed else "1/2",
            )

    result = _invoke_compare(tmp_path)
    assert result.exit_code == 0, result.output
    assert "ctx-rm" in result.output
    assert "minimal" in result.output


def test_compare_handles_missing_evaluation(tmp_path: Path) -> None:
    """compare does not crash when evaluation.json is missing; shows --."""
    leaf = tmp_path / "CR-001" / "full" / "gemini"
    _write_metrics(leaf / "run-1" / "metrics.json")
    # No evaluation.json written

    result = _invoke_compare(tmp_path)
    assert result.exit_code == 0, result.output
    assert "CR-001" in result.output
    assert "--" in result.output


def test_compare_handles_partial_runs(tmp_path: Path) -> None:
    """compare handles run dirs where some have metrics but no evaluation."""
    base = tmp_path / "CR-001" / "minimal" / "gemini"
    _write_metrics(base / "run-1" / "metrics.json", tokens_in=100)
    _write_evaluation(base / "run-1" / "evaluation.json", all_passed=True, summary="2/2")

    _write_metrics(base / "run-2" / "metrics.json", tokens_in=200)
    # run-2 has no evaluation.json — partial data

    _write_metrics(base / "run-3" / "metrics.json", tokens_in=300)
    _write_evaluation(base / "run-3" / "evaluation.json", all_passed=False, summary="1/2")

    result = _invoke_compare(tmp_path)
    assert result.exit_code == 0, result.output
    # Pass rate based on evals only: 1 passed out of 2 evaluated
    assert "1/2" in result.output


def test_compare_missing_dir(tmp_path: Path) -> None:
    """compare exits with error for nonexistent directory."""
    result = runner.invoke(app, ["compare", str(tmp_path / "nonexistent")])
    assert result.exit_code == 1


def test_compare_empty_results(tmp_path: Path) -> None:
    """compare with no results shows 'No results found'."""
    result = runner.invoke(app, ["compare", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "No results found" in result.output


# ── tasks tests ──────────────────────────────────────────────────────────────


def test_tasks_lists_all_benchmark_tasks() -> None:
    """tasks command lists all benchmark tasks including phase-7 additions."""
    result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 0, result.output
    assert "CR-001" in result.output
    assert "CR-010" in result.output
    assert "MULTI-001" in result.output
    assert "TRACE-001" in result.output
    assert "SPEC-001" in result.output
    assert "13 tasks available" in result.output


# ── info tests ───────────────────────────────────────────────────────────────


def test_info_shows_version_and_components() -> None:
    """info command shows version, policies, and scorer."""
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0, result.output
    assert "ctx-rm" in result.output
    assert "budget" in result.output
    assert "heuristic" in result.output


# ── llamacpp driver routing ─────────────────────────────────────────────────


@patch("ctx_rm.drivers.gemini.GeminiCLIDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.drivers.claude.ClaudeCodeDriver.check_available", new_callable=AsyncMock, return_value=False)
@patch("ctx_rm.drivers.llamacpp.LlamaCppDriver.check_available", new_callable=AsyncMock, return_value=True)
@patch("ctx_rm.benchmarks.loader.TaskLoader.list_task_ids", return_value=["CR-001"])
@patch("ctx_rm.benchmarks.runner.AgentLoopRunner")
def test_bench_all_uses_agent_loop_runner_for_llamacpp(
    mock_agent_runner_cls: MagicMock,
    _mock_loader: MagicMock,
    _mock_llamacpp: AsyncMock,
    _mock_claude: AsyncMock,
    _mock_gemini: AsyncMock,
) -> None:
    """--all with only llamacpp available uses AgentLoopRunner."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_agent_runner_cls.return_value = mock_instance

    result = runner.invoke(app, ["bench", "--all"])
    assert result.exit_code == 0, result.output
    # 1 task x 3 modes x 1 driver (llamacpp) = 3 calls
    assert mock_agent_runner_cls.call_count == 3
    assert "3/3" in result.output
    # Verify driver_name is llamacpp
    for call in mock_agent_runner_cls.call_args_list:
        assert call.kwargs["driver_name"] == "llamacpp"


@patch("ctx_rm.benchmarks.runner.AgentLoopRunner")
def test_bench_llamacpp_routes_to_agent_loop_runner(mock_runner_cls: MagicMock) -> None:
    """--driver llamacpp uses AgentLoopRunner instead of BenchmarkRunner."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    result = runner.invoke(app, ["bench", "--driver", "llamacpp", "--task", "CR-001"])
    assert result.exit_code == 0, result.output
    mock_runner_cls.assert_called_once()
    call_kwargs = mock_runner_cls.call_args.kwargs
    assert call_kwargs["driver_name"] == "llamacpp"


@patch("ctx_rm.benchmarks.runner.AgentLoopRunner")
def test_bench_llamacpp_passes_recall_and_max_turns(mock_runner_cls: MagicMock) -> None:
    """Recall and max turns flags should be forwarded to AgentLoopRunner."""
    mock_instance = MagicMock()
    mock_instance.run = AsyncMock()
    mock_runner_cls.return_value = mock_instance

    result = runner.invoke(
        app,
        [
            "bench",
            "--driver",
            "llamacpp",
            "--task",
            "CR-001",
            "--enable-recall",
            "--max-turns",
            "42",
        ],
    )
    assert result.exit_code == 0, result.output
    call_kwargs = mock_runner_cls.call_args.kwargs
    assert call_kwargs["enable_recall"] is True
    assert call_kwargs["max_turns"] == 42


def test_bench_rejects_invalid_driver() -> None:
    """Invalid driver value is rejected by the enum."""
    result = runner.invoke(app, ["bench", "--driver", "invalid"])
    assert result.exit_code != 0
