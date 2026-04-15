"""Unit tests for the Claude Code loader and normalizer.

Tests run against small hand-built transcripts rather than the real
~/.claude/projects/ files so the suite is hermetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctx_rm.eval.trace.claude_code import load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.schema import TraceSegmentKind


def _write_jsonl(path: Path, events: list[dict]) -> None:
    with path.open("w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


def _user_text(uuid: str, text: str) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "timestamp": "2026-04-15T10:00:00Z",
        "sessionId": "test-session",
        "cwd": "/tmp/test",
        "message": {"role": "user", "content": text},
    }


def _assistant_blocks(uuid: str, blocks: list[dict]) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": "2026-04-15T10:00:01Z",
        "sessionId": "test-session",
        "message": {"model": "claude-test", "role": "assistant", "content": blocks},
    }


def _tool_result(uuid: str, tool_use_id: str, text: str) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "timestamp": "2026-04-15T10:00:02Z",
        "sessionId": "test-session",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": text,
                }
            ],
        },
    }


class TestLoader:
    def test_loads_well_formed_events(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(p, [_user_text("u1", "hello")])
        loaded = load_transcript(p)
        assert loaded.num_events == 1
        assert loaded.session_id == "test-session"
        assert loaded.cwd == "/tmp/test"

    def test_skips_unsupported_event_types(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(
            p,
            [
                {"type": "permission-mode", "sessionId": "x"},
                _user_text("u1", "hi"),
                {"type": "file-history-snapshot", "sessionId": "x"},
            ],
        )
        loaded = load_transcript(p)
        assert loaded.num_events == 1
        assert loaded.skipped_types == {
            "permission-mode": 1,
            "file-history-snapshot": 1,
        }

    def test_tolerates_malformed_json_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        p.write_text('{"type": "user", "message": {"content": "ok"}}\n{bad line\n')
        loaded = load_transcript(p)
        # Bad line is counted, good line survives.
        assert loaded.num_events == 1
        assert loaded.skipped_types.get("_malformed_json") == 1


class TestNormalize:
    def test_string_user_produces_single_segment(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(p, [_user_text("u1", "hello")])
        trace = normalize(load_transcript(p), project="test")
        assert len(trace.segments) == 1
        assert trace.segments[0].kind == TraceSegmentKind.USER
        assert trace.segments[0].content == "hello"
        assert trace.segments[0].turn_index == 0

    def test_assistant_multiblock_splits(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(
            p,
            [
                _user_text("u1", "do the thing"),
                _assistant_blocks(
                    "a1",
                    [
                        {"type": "text", "text": "sure"},
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "Read",
                            "input": {"file_path": "/a.py"},
                        },
                    ],
                ),
            ],
        )
        trace = normalize(load_transcript(p), project="test")
        kinds = [s.kind for s in trace.segments]
        assert kinds == [
            TraceSegmentKind.USER,
            TraceSegmentKind.ASSISTANT_TEXT,
            TraceSegmentKind.TOOL_USE,
        ]
        # Assistant's blocks share a turn with the user that preceded them.
        assert {s.turn_index for s in trace.segments} == {0}
        tool_use = trace.segments[-1]
        assert tool_use.tool_name == "Read"
        assert tool_use.source_file == "/a.py"
        assert tool_use.tool_use_id == "tool_1"

    def test_tool_result_gets_new_turn(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(
            p,
            [
                _user_text("u1", "go"),
                _assistant_blocks(
                    "a1",
                    [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Read",
                            "input": {"file_path": "/x.py"},
                        }
                    ],
                ),
                _tool_result("u2", "t1", "file contents"),
                _assistant_blocks("a2", [{"type": "text", "text": "done"}]),
            ],
        )
        trace = normalize(load_transcript(p), project="test")
        turns = [(s.kind.value, s.turn_index) for s in trace.segments]
        # user + tool_use share turn 0 (one LLM call)
        # tool_result + assistant_text share turn 1 (next LLM call)
        assert turns == [
            ("user", 0),
            ("tool_use", 0),
            ("tool_result", 1),
            ("assistant_text", 1),
        ]

    def test_consecutive_assistant_events_coalesce(self, tmp_path: Path) -> None:
        """Claude Code often splits one response into multiple assistant events
        (thinking in one, tool_use in another). They should share a turn.
        """
        p = tmp_path / "t.jsonl"
        _write_jsonl(
            p,
            [
                _user_text("u1", "go"),
                _assistant_blocks("a1", [{"type": "thinking", "thinking": "hmm"}]),
                _assistant_blocks("a2", [{"type": "text", "text": "ok"}]),
                _user_text("u2", "next"),
            ],
        )
        trace = normalize(load_transcript(p), project="test")
        assert len(trace.segments) == 4
        turns = [s.turn_index for s in trace.segments]
        # user, thinking, text all in turn 0; the "next" user in turn 1.
        assert turns == [0, 0, 0, 1]

    def test_seg_ids_are_stable_across_reloads(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(
            p,
            [_user_text("u1", "hello"), _user_text("u2", "world")],
        )
        a = normalize(load_transcript(p), project="test")
        b = normalize(load_transcript(p), project="test")
        assert [s.seg_id for s in a.segments] == [s.seg_id for s in b.segments]


class TestRealTraceSmoke:
    """A smoke test against the real ctx-rm session if it exists on disk."""

    _REAL_TRACE = Path(
        "/home/akougkas/.claude/projects/-home-akougkas-projects-ctx-rm/"
        "68e1be56-c100-43ef-8d88-86b218a307d4.jsonl"
    )

    @pytest.mark.skipif(not _REAL_TRACE.exists(), reason="real ctx-rm trace not on disk")
    def test_loads_without_error(self) -> None:
        loaded = load_transcript(self._REAL_TRACE)
        trace = normalize(loaded, project="ctx-rm")
        assert trace.num_turns > 0
        assert len(trace.segments) > 0
        assert trace.model is not None
