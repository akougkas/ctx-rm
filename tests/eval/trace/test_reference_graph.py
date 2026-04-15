"""Tests for the reference graph.

Each test builds a tiny hand-crafted Trace with known reference relationships,
then checks that the graph recovers them under the expected mode.
"""

from __future__ import annotations

from ctx_rm.eval.trace.reference_graph import (
    ReferenceEdgeKind,
    ReferenceGraph,
    ReferenceMode,
)
from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind


def _seg(
    seg_id: str,
    turn: int,
    event: int,
    kind: TraceSegmentKind,
    content: str,
    *,
    tool_name: str | None = None,
    tool_use_id: str | None = None,
    source_file: str | None = None,
) -> TraceSegment:
    return TraceSegment(
        seg_id=seg_id,
        turn_index=turn,
        event_index=event,
        timestamp=float(event),
        kind=kind,
        content=content,
        token_count=max(1, len(content) // 4),
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        source_file=source_file,
    )


def _trace(segs: list[TraceSegment]) -> Trace:
    return Trace(trace_id="test", source_path="mem", project="test", segments=segs)


class TestFileRereadEdge:
    def test_later_tool_use_on_same_file_creates_edge(self) -> None:
        segs = [
            _seg(
                "tu1",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a.py",
                tool_name="Read",
                tool_use_id="id1",
                source_file="/a.py",
            ),
            _seg(
                "tr1",
                1,
                1,
                TraceSegmentKind.TOOL_RESULT,
                "contents of a",
                tool_use_id="id1",
            ),
            # A lot of intervening noise
            _seg(
                "noise",
                2,
                2,
                TraceSegmentKind.ASSISTANT_TEXT,
                "working on it",
            ),
            _seg(
                "tu2",
                3,
                3,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a.py",
                tool_name="Read",
                tool_use_id="id2",
                source_file="/a.py",
            ),
        ]
        graph = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        kinds = {e.kind for e in graph.edges}
        assert ReferenceEdgeKind.FILE_REREAD in kinds
        # Both the earlier tool_use and its tool_result should be referenced.
        assert graph.is_referenced_after("tu1", turn=2)
        assert graph.is_referenced_after("tr1", turn=2)
        assert not graph.is_referenced_after("noise", turn=2)

    def test_no_edge_when_paths_differ(self) -> None:
        segs = [
            _seg(
                "tu1",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a.py",
                tool_name="Read",
                source_file="/a.py",
            ),
            _seg(
                "tu2",
                1,
                1,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/b.py",
                tool_name="Read",
                source_file="/b.py",
            ),
        ]
        graph = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert graph.num_edges == 0


class TestFileRereadDirectoryGuard:
    def test_glob_pattern_path_does_not_create_edge(self) -> None:
        segs = [
            _seg(
                "tu1",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Glob pattern=**/shared.ts path=/awoc",
                tool_name="Glob",
                source_file="/awoc",
            ),
            _seg(
                "tu2",
                1,
                1,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Glob pattern=**/cli.ts path=/awoc",
                tool_name="Glob",
                source_file="/awoc",
            ),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert all(e.kind != ReferenceEdgeKind.FILE_REREAD for e in g.edges)

    def test_literal_file_path_still_creates_edge(self) -> None:
        segs = [
            _seg(
                "tu1",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a/b/c.py",
                tool_name="Read",
                source_file="/a/b/c.py",
            ),
            _seg(
                "tu2",
                1,
                1,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a/b/c.py",
                tool_name="Read",
                source_file="/a/b/c.py",
            ),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert any(e.kind == ReferenceEdgeKind.FILE_REREAD for e in g.edges)


class TestExactQuoteEdge:
    def test_later_text_quoting_tool_result(self) -> None:
        result_text = (
            "The function authenticate_user_with_token returns a JWT bearer "
            "after validating the signature against the public key"
        )
        segs = [
            _seg(
                "tr1",
                0,
                0,
                TraceSegmentKind.TOOL_RESULT,
                result_text,
                tool_use_id="id1",
            ),
            _seg(
                "at1",
                1,
                1,
                TraceSegmentKind.ASSISTANT_TEXT,
                "Looking at authenticate_user_with_token, it returns a JWT "
                "bearer after validating the signature.",
            ),
        ]
        graph = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        kinds = {e.kind for e in graph.edges}
        assert ReferenceEdgeKind.EXACT_QUOTE in kinds
        assert graph.is_referenced_after("tr1", turn=0)

    def test_unrelated_text_does_not_match(self) -> None:
        segs = [
            _seg(
                "tr1",
                0,
                0,
                TraceSegmentKind.TOOL_RESULT,
                "result alpha bravo charlie delta echo foxtrot golf hotel",
                tool_use_id="id1",
            ),
            _seg(
                "at1",
                1,
                1,
                TraceSegmentKind.ASSISTANT_TEXT,
                "entirely different topic about kubernetes networking stanzas",
            ),
        ]
        graph = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert ReferenceEdgeKind.EXACT_QUOTE not in {e.kind for e in graph.edges}


class TestExactQuoteSourceGuard:
    def test_glob_tool_result_is_not_a_quote_source(self) -> None:
        segs = [
            _seg(
                "tu_glob",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Glob pattern=**/*.py",
                tool_name="Glob",
                tool_use_id="g1",
                source_file="/home/akougkas/projects/ctx-rm",
            ),
            _seg(
                "tr_glob",
                0,
                1,
                TraceSegmentKind.TOOL_RESULT,
                "/home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py\n"
                "/home/akougkas/projects/ctx-rm/src/ctx_rm/core/segment.py",
                tool_use_id="g1",
            ),
            _seg(
                "tu_read",
                1,
                2,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py",
                tool_name="Read",
                tool_use_id="r1",
                source_file="/home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py",
            ),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert all(e.kind != ReferenceEdgeKind.EXACT_QUOTE for e in g.edges)

    def test_short_error_result_is_not_a_quote_source(self) -> None:
        segs = [
            _seg(
                "tu",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/nope.py",
                tool_name="Read",
                tool_use_id="x",
                source_file="/nope.py",
            ),
            _seg(
                "tr",
                0,
                1,
                TraceSegmentKind.TOOL_RESULT,
                "File does not exist.",
                tool_use_id="x",
            ),
            _seg(
                "tu2",
                1,
                2,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Bash command=ls /nope.py",
                tool_name="Bash",
                tool_use_id="b1",
            ),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert all(e.kind != ReferenceEdgeKind.EXACT_QUOTE for e in g.edges)

    def test_path_only_shared_content_is_not_an_edge(self) -> None:
        segs = [
            _seg(
                "tr",
                0,
                0,
                TraceSegmentKind.TOOL_RESULT,
                "Running in /home/akougkas/projects/awoc/src. Done.",
                tool_use_id="x",
            ),
            _seg(
                "tu",
                1,
                1,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/home/akougkas/projects/awoc/src/cli.ts",
                tool_name="Read",
                tool_use_id="y",
                source_file="/home/akougkas/projects/awoc/src/cli.ts",
            ),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert g.num_edges == 0


class TestAmbientTokenFilter:
    def test_identifier_in_most_results_does_not_gate_quote(self) -> None:
        result_bodies = [
            "SessionManager initialized. Some long unique content-A here "
            "with enough characters to clear the stripped-length gate.",
            "SessionManager starting. Unrelated body-B with another set of "
            "words padding the stripped length over forty chars easily.",
            "SessionManager shutdown. Totally distinct body-C also longer "
            "than forty characters after path stripping, guaranteed.",
            "SessionManager waiting. Yet another body-D with its own padding "
            "so every result clears the stripped length threshold.",
        ]
        segs: list[TraceSegment] = []
        for i, body in enumerate(result_bodies):
            segs.append(
                _seg(
                    f"tu{i}",
                    i,
                    i * 2,
                    TraceSegmentKind.TOOL_USE,
                    "tool_use:Read file_path=/x.py",
                    tool_name="Read",
                    tool_use_id=f"id{i}",
                    source_file="/x.py",
                )
            )
            segs.append(
                _seg(
                    f"tr{i}",
                    i,
                    i * 2 + 1,
                    TraceSegmentKind.TOOL_RESULT,
                    body,
                    tool_use_id=f"id{i}",
                )
            )
        segs.append(
            _seg(
                "at",
                4,
                999,
                TraceSegmentKind.ASSISTANT_TEXT,
                "SessionManager was invoked twice and the handler exited "
                "cleanly after draining the queue, writing the final log.",
            )
        )
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        for e in g.edges:
            assert e.kind != ReferenceEdgeKind.EXACT_QUOTE or e.target_seg_id != "at"

    def test_distinctive_identifier_still_gates_quote(self) -> None:
        unique = "authenticate_user_with_token_v42"
        segs = [
            _seg(
                "tu",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/auth.py",
                tool_name="Read",
                tool_use_id="id1",
                source_file="/auth.py",
            ),
            _seg(
                "tr",
                0,
                1,
                TraceSegmentKind.TOOL_RESULT,
                f"The function {unique} returns a JWT bearer token "
                f"after validating the signature against the public key.",
                tool_use_id="id1",
            ),
            _seg(
                "at",
                1,
                2,
                TraceSegmentKind.ASSISTANT_TEXT,
                f"Looking at {unique}, it returns a JWT bearer token "
                f"after validating the signature.",
            ),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert any(e.kind == ReferenceEdgeKind.EXACT_QUOTE for e in g.edges)


class TestLenientNgramEdge:
    def test_shared_ngram_creates_lenient_edge(self) -> None:
        shared = "async function dispatches worker threads across multiple queues"
        segs = [
            _seg(
                "a",
                0,
                0,
                TraceSegmentKind.ASSISTANT_TEXT,
                f"The {shared} using a central coordinator",
            ),
            _seg(
                "b",
                1,
                1,
                TraceSegmentKind.ASSISTANT_TEXT,
                f"We implement the {shared} inside the handler",
            ),
        ]
        strict = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        lenient = ReferenceGraph.build(_trace(segs), ReferenceMode.LENIENT)
        # Strict may or may not catch this; lenient definitely should.
        assert lenient.num_edges >= strict.num_edges
        assert ReferenceEdgeKind.NGRAM_OVERLAP in {e.kind for e in lenient.edges}

    def test_lenient_has_more_edges_than_strict_on_real_content(self) -> None:
        content_a = (
            "The ContextBus admission control routes large file_read tool "
            "segments to the Warm tier to prevent scan pollution in active."
        )
        content_b = (
            "To prevent scan pollution in active context, ContextBus admission "
            "control sends large file_read tool segments straight to Warm."
        )
        segs = [
            _seg("a", 0, 0, TraceSegmentKind.ASSISTANT_TEXT, content_a),
            _seg("b", 1, 1, TraceSegmentKind.ASSISTANT_TEXT, content_b),
        ]
        strict = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        lenient = ReferenceGraph.build(_trace(segs), ReferenceMode.LENIENT)
        assert lenient.num_edges >= strict.num_edges


class TestPublicAPI:
    def test_earliest_future_turn_returns_int_for_referenced_seg(self) -> None:
        segs = [
            _seg(
                "tu1",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a.py",
                tool_name="Read",
                source_file="/a.py",
            ),
            _seg(
                "tu2",
                3,
                1,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a.py",
                tool_name="Read",
                source_file="/a.py",
            ),
        ]
        g = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert g.earliest_future_turn("tu1") == 3
        assert g.earliest_future_turn("tu2") is None


class TestSelfReferenceExcluded:
    def test_no_self_edge(self) -> None:
        segs = [
            _seg(
                "x",
                0,
                0,
                TraceSegmentKind.TOOL_USE,
                "tool_use:Read file_path=/a.py",
                source_file="/a.py",
            ),
        ]
        graph = ReferenceGraph.build(_trace(segs), ReferenceMode.STRICT)
        assert graph.num_edges == 0
