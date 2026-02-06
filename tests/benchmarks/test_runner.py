"""Tests for the refactored BenchmarkRunner with mocked driver."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import orjson

from ctx_rm.benchmarks.runner import BenchmarkRunner
from ctx_rm.drivers.base import AgentDriver, AgentResponse

YAML_PATH = Path("docs/context_removal_benchmark_tasks.yaml")
FIXTURES_ROOT = Path("benchmarks/fixtures")


def _make_mock_driver() -> AsyncMock:
    """Create a mock AgentDriver that returns canned responses."""
    driver = AsyncMock(spec=AgentDriver)
    driver.name = "mock"
    driver.check_available = AsyncMock(return_value=True)
    driver.invoke = AsyncMock(return_value=AgentResponse(
        text="mock response",
        prompt_tokens=100,
        completion_tokens=50,
        tool_calls=1,
        success=True,
    ))
    return driver


def _make_runner(tmp_path: Path, mode: str = "minimal") -> tuple[BenchmarkRunner, AsyncMock]:
    """Build a BenchmarkRunner with a mock driver patched in."""
    runner = BenchmarkRunner(
        driver_name="gemini",
        task_id="CR-001",
        mode=mode,
        output_dir=tmp_path,
        yaml_path=YAML_PATH,
        fixtures_root=FIXTURES_ROOT,
    )
    mock_driver = _make_mock_driver()
    runner._create_driver = lambda: mock_driver  # type: ignore[assignment]
    return runner, mock_driver


def test_run_creates_nested_output_dir(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path, mode="minimal")
    asyncio.run(runner.run())
    assert (tmp_path / "CR-001" / "minimal" / "gemini").is_dir()


def test_run_writes_metrics_json(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path, mode="minimal")
    asyncio.run(runner.run())
    metrics_path = tmp_path / "CR-001" / "minimal" / "gemini" / "metrics.json"
    assert metrics_path.exists()
    data = orjson.loads(metrics_path.read_bytes())
    assert "summary" in data


def test_run_writes_evaluation_json(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path, mode="minimal")
    asyncio.run(runner.run())
    eval_path = tmp_path / "CR-001" / "minimal" / "gemini" / "evaluation.json"
    assert eval_path.exists()
    data = orjson.loads(eval_path.read_bytes())
    assert data["task_id"] == "CR-001"
    assert isinstance(data["all_passed"], bool)
    assert isinstance(data["checks"], list)


def test_run_writes_response_log(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path, mode="minimal")
    asyncio.run(runner.run())
    log_path = tmp_path / "CR-001" / "minimal" / "gemini" / "response_log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    # CR-001 has min_turns=20
    assert len(lines) == 20
    first = orjson.loads(lines[0])
    assert "turn" in first
    assert "prompt_len" in first
    assert "response_text" in first
    assert "success" in first


def test_fixture_cleanup_after_run(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path, mode="minimal")
    # Count ctx-rm temp dirs before
    before = set(Path(tempfile.gettempdir()).glob("ctx-rm-legacy_flag_cascade-*"))
    asyncio.run(runner.run())
    after = set(Path(tempfile.gettempdir()).glob("ctx-rm-legacy_flag_cascade-*"))
    # No new leftover dirs (cleanup happened)
    new_dirs = after - before
    assert len(new_dirs) == 0, f"Leftover temp dirs: {new_dirs}"


def test_full_mode_runs(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path, mode="full")
    asyncio.run(runner.run())
    result_dir = tmp_path / "CR-001" / "full" / "gemini"
    assert (result_dir / "metrics.json").exists()
    assert (result_dir / "evaluation.json").exists()
    assert (result_dir / "response_log.jsonl").exists()


def test_driver_receives_fixture_working_dir(tmp_path: Path) -> None:
    runner, mock_driver = _make_runner(tmp_path, mode="minimal")
    asyncio.run(runner.run())
    # Every invoke call should use the fixture temp dir, not "."
    for call in mock_driver.invoke.call_args_list:
        working_dir = call.kwargs.get("working_dir")
        if working_dir is None and len(call.args) > 2:
            working_dir = call.args[2]
        assert working_dir != "."
        assert "ctx-rm-legacy_flag_cascade" in working_dir


def test_response_log_entries_have_all_fields(tmp_path: Path) -> None:
    """Verify every JSONL entry contains the full schema."""
    runner, _ = _make_runner(tmp_path, mode="full")
    asyncio.run(runner.run())
    log_path = tmp_path / "CR-001" / "full" / "gemini" / "response_log.jsonl"
    expected_keys = {
        "turn", "prompt_len", "response_text", "prompt_tokens",
        "completion_tokens", "tool_calls", "elapsed_ms", "success", "timestamp",
    }
    for line in log_path.read_text().strip().splitlines():
        entry = orjson.loads(line)
        assert expected_keys.issubset(entry.keys()), f"Missing keys: {expected_keys - entry.keys()}"


def test_create_scorer_defaults_to_heuristic(tmp_path: Path) -> None:
    """Default config.scorer='heuristic' means _create_scorer returns HeuristicScorer."""
    runner, _ = _make_runner(tmp_path, mode="ctx-rm")
    from ctx_rm.core.scorer import HeuristicScorer

    scorer = runner._create_scorer()
    assert isinstance(scorer, HeuristicScorer)


def test_runner_imports_embedding_provider() -> None:
    """BenchmarkRunner imports HashingEmbeddingProvider for ctx-rm mode."""
    from ctx_rm.benchmarks.runner import HashingEmbeddingProvider
    from ctx_rm.core.embedding import EmbeddingProvider

    provider = HashingEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)
