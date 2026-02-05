"""Tests for the TurnExecutor with needle and noise injection."""

from pathlib import Path

from ctx_rm.benchmarks.executor import CHARS_PER_TOKEN, TurnExecutor, generate_noise
from ctx_rm.benchmarks.loader import TaskLoader

YAML_PATH = Path("docs/context_removal_benchmark_tasks.yaml")


def _load_task(task_id: str):
    return TaskLoader(YAML_PATH).get_task(task_id)


def test_build_turns_count() -> None:
    task = _load_task("CR-001")
    turns = TurnExecutor().build_turns(task)
    assert len(turns) == 20


def test_needle_injection_at_correct_turn() -> None:
    task = _load_task("CR-001")
    turns = TurnExecutor().build_turns(task)
    # N1 at turn 3
    assert "SAFE_MODE must remain true" in turns[2].prompt
    # Not in turn 2
    assert "SAFE_MODE must remain true" not in turns[1].prompt


def test_second_needle_injection() -> None:
    task = _load_task("CR-001")
    turns = TurnExecutor().build_turns(task)
    # N2 at turn 7
    assert "config/flags.py contains SAFE_MODE" in turns[6].prompt


def test_noise_injection_size() -> None:
    task = _load_task("CR-001")
    turns = TurnExecutor().build_turns(task)
    # context_injection at turn 10, size_tokens=2500
    assert len(turns[9].prompt) >= 2500 * CHARS_PER_TOKEN
    # turn 9 has no noise — should be much shorter
    assert len(turns[8].prompt) < 2500 * CHARS_PER_TOKEN


def test_generate_noise_length() -> None:
    result = generate_noise(1000)
    assert len(result) == 1000 * CHARS_PER_TOKEN


def test_multiple_injections_same_task() -> None:
    task = _load_task("CR-004")
    turns = TurnExecutor().build_turns(task)
    # context_injection at turn 4, 5000 tokens
    assert len(turns[3].prompt) >= 5000 * CHARS_PER_TOKEN
    # context_injection at turn 9, 3000 tokens
    assert len(turns[8].prompt) >= 3000 * CHARS_PER_TOKEN
    # needle at turn 12
    assert "NoneType in cache.invalidate" in turns[11].prompt


def test_all_turns_have_base_prompt() -> None:
    task = _load_task("CR-001")
    turns = TurnExecutor().build_turns(task)
    for turn in turns:
        assert "Continue working on:" in turn.prompt
