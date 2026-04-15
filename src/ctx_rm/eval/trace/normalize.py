"""Normalize Claude Code raw events into canonical TraceSegments.

Policy:

- One Claude Code event may produce multiple TraceSegments. An assistant
  event with `content=[thinking, text, tool_use, tool_use]` becomes four
  segments that all share the same `turn_index` but have strictly monotonic
  `event_index`. This lets policies evict individual tool_use blocks while
  preserving the invariant that a turn_index boundary means "an LLM call
  happened here".
- Tool results are grouped under user events by Claude Code. We split them
  into TOOL_RESULT segments keyed by `tool_use_id` so the reference graph
  can stitch them back to the tool_use that produced them.
- Turn index advances on every assistant event. Segments before the first
  assistant event get turn_index = 0.
- Tokens are estimated with ctx_rm.core.tokenizer.estimate_tokens so replay
  results are consistent with the runtime bus.
- `source_file` is populated for tool_use blocks whose name matches a
  file-reading tool (Read, Glob, Grep, ...) and whose input contains a
  path-like key. This is a best-effort heuristic used by the strict
  reference graph.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from ctx_rm.core.tokenizer import estimate_tokens
from ctx_rm.eval.trace.claude_code import LoadedTranscript, RawEvent
from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind

# Tools whose input carries a file path we should lift into source_file.
_FILE_PATH_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit", "Glob", "Grep", "MultiEdit"})
# Keys we accept as holding a file path, in priority order.
_PATH_KEYS = ("file_path", "path", "notebook_path")


def _parse_timestamp(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        # Claude Code uses RFC 3339 with trailing Z; fromisoformat handles it
        # after replacing the Z.
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _stable_seg_id(
    trace_id: str, turn_index: int, event_index: int, kind: str, content: str
) -> str:
    """Deterministic id: repeatable across reloads, unique within a trace."""
    h = hashlib.sha1(usedforsecurity=False)
    h.update(trace_id.encode())
    h.update(b"|")
    h.update(str(turn_index).encode())
    h.update(b"|")
    h.update(str(event_index).encode())
    h.update(b"|")
    h.update(kind.encode())
    h.update(b"|")
    h.update(content[:2048].encode(errors="replace"))
    return h.hexdigest()[:16]


def _extract_path(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    if tool_name not in _FILE_PATH_TOOLS:
        return None
    for key in _PATH_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _stringify_tool_use(name: str, tool_input: dict[str, Any]) -> str:
    """Serialize a tool_use block into text for scoring/tokenization.

    We don't use JSON because the scorer's lexical path produces better
    redundancy signals on natural text. The format is stable so two identical
    tool_uses produce the same content hash.
    """
    parts = [f"tool_use:{name}"]
    for k in sorted(tool_input.keys()):
        v = tool_input[k]
        if isinstance(v, str):
            parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={v!r}")
    return "\n".join(parts)


def _flatten_tool_result_content(content: Any) -> str:
    """Tool results may be str, a list of blocks, or a nested structure."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block and isinstance(block["text"], str):
                    out.append(block["text"])
                elif block.get("type") == "image":
                    out.append("[image]")
                else:
                    out.append(str(block))
            else:
                out.append(str(block))
        return "\n".join(out)
    return str(content)


def _normalize_event(
    event: RawEvent,
    *,
    trace_id: str,
    turn_index: int,
    event_index_start: int,
) -> list[TraceSegment]:
    """Convert one raw event into zero or more TraceSegments.

    Returns a list so the caller can splice the segments into the global
    stream and bump `event_index` by len(result).
    """
    ts = _parse_timestamp(event.timestamp_iso)
    segments: list[TraceSegment] = []
    msg = event.raw.get("message")
    if not isinstance(msg, dict):
        return []

    content = msg.get("content")

    def _new(kind: TraceSegmentKind, text: str, **extra: Any) -> TraceSegment:
        nonlocal event_index_start
        ei = event_index_start + len(segments)
        seg = TraceSegment(
            seg_id=_stable_seg_id(trace_id, turn_index, ei, kind.value, text),
            turn_index=turn_index,
            event_index=ei,
            timestamp=ts,
            kind=kind,
            content=text,
            token_count=estimate_tokens(text) if text else 0,
            raw_event_uuid=event.uuid,
            parent_event_uuid=event.parent_uuid,
            **extra,
        )
        return seg

    etype = event.type

    if etype == "system":
        text = content if isinstance(content, str) else str(content or "")
        if text:
            segments.append(_new(TraceSegmentKind.SYSTEM, text))
        return segments

    if etype == "attachment":
        # Attachments carry file context the user dropped into the session.
        # Content shape varies; coerce to text.
        text = content if isinstance(content, str) else str(content or "")
        if not text and "attachment" in event.raw:
            text = str(event.raw.get("attachment", ""))
        if text:
            segments.append(_new(TraceSegmentKind.ATTACHMENT, text))
        return segments

    if etype == "user":
        # Two possibilities: a plain user prompt (string content) or a
        # tool_result carrier (list content).
        if isinstance(content, str):
            if content.strip():
                segments.append(_new(TraceSegmentKind.USER, content))
            return segments
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_result":
                    text = _flatten_tool_result_content(block.get("content", ""))
                    tool_use_id = block.get("tool_use_id")
                    segments.append(
                        _new(
                            TraceSegmentKind.TOOL_RESULT,
                            text,
                            tool_use_id=tool_use_id,
                        )
                    )
                elif btype == "text":
                    text = block.get("text", "")
                    if text:
                        segments.append(_new(TraceSegmentKind.USER, text))
            return segments
        return segments

    if etype == "assistant":
        if not isinstance(content, list):
            return segments
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text:
                    segments.append(_new(TraceSegmentKind.ASSISTANT_TEXT, text))
            elif btype == "thinking":
                text = block.get("thinking", "")
                if text:
                    segments.append(_new(TraceSegmentKind.ASSISTANT_THINKING, text))
            elif btype == "tool_use":
                name = block.get("name", "")
                tool_input = block.get("input") or {}
                if not isinstance(tool_input, dict):
                    tool_input = {}
                text = _stringify_tool_use(name, tool_input)
                source_file = _extract_path(name, tool_input)
                segments.append(
                    _new(
                        TraceSegmentKind.TOOL_USE,
                        text,
                        tool_name=name,
                        tool_use_id=block.get("id"),
                        source_file=source_file,
                    )
                )
        return segments

    return segments


def normalize(loaded: LoadedTranscript, project: str) -> Trace:
    """Walk a LoadedTranscript and emit a canonical Trace.

    turn_index advances when the event stream transitions *out of* an
    assistant block into a non-assistant event (user / tool_result /
    attachment). Claude Code emits each thinking/text/tool_use block as its
    own assistant event, so naively bumping on every assistant event would
    inflate the turn count and misalign the eviction-cycle boundaries.
    Coalescing consecutive assistant events into one turn matches the "one
    LLM call, one logical turn" model.
    """
    segments: list[TraceSegment] = []
    event_index = 0
    turn_index = 0
    prev_was_assistant = False

    for event in loaded.events:
        # Transition from assistant run → other event: the LLM call that
        # produced the prior assistant block is now complete.
        if prev_was_assistant and event.type != "assistant":
            turn_index += 1

        new_segs = _normalize_event(
            event,
            trace_id=loaded.session_id,
            turn_index=turn_index,
            event_index_start=event_index,
        )
        segments.extend(new_segs)
        event_index += len(new_segs)
        prev_was_assistant = event.type == "assistant"

    return Trace(
        trace_id=loaded.session_id,
        source_path=loaded.path,
        project=project,
        cwd=loaded.cwd,
        model=loaded.model,
        cli_version=loaded.cli_version,
        git_branch=loaded.git_branch,
        segments=segments,
    )
