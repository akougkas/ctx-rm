"""Canonical trace schema.

A `Trace` is a recorded agent session normalized from some upstream format
(Claude Code JSONL today, more providers later). It is the single input to
every tier of the eval suite so that policies and metrics never touch raw
provider-specific data.

Design notes
------------
- **Stable seg_ids.** Computed from (turn_index, kind, content hash). Stable
  across reloads of the same file and across the strict/lenient reference
  graph variants.
- **Per-block segments.** A Claude Code `assistant` event often contains a
  thinking block + a text block + several tool_use blocks. Each block becomes
  its own TraceSegment so eviction can happen at block granularity. A `user`
  event containing tool_results is split the same way.
- **Turn index ≠ event index.** Multiple segments can share the same turn
  index when they originated from the same upstream event. The runner uses
  turn index as the "LLM call boundary" because every assistant event maps to
  exactly one LLM call.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TraceSegmentKind(StrEnum):
    """The structural role of a segment inside a recorded trace.

    This is a finer taxonomy than ctx_rm.core.segment.SegmentRole because the
    eval layer needs to distinguish tool_use (an agent decision) from
    tool_result (environment output) even though both map to the "tool" role
    at the bus level.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT_TEXT = "assistant_text"
    ASSISTANT_THINKING = "assistant_thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    ATTACHMENT = "attachment"


class TraceSegment(BaseModel):
    """A single content block extracted from a recorded trace.

    Fields map cleanly onto `ctx_rm.core.segment.Segment` when the replay
    runner ingests them — the runner constructs a Segment from each
    TraceSegment at replay time, not here. Keeping the two types separate
    lets us load and label traces without importing the runtime.
    """

    seg_id: str
    turn_index: int = Field(
        description=(
            "Monotonic index into the ordered stream of assistant LLM calls. "
            "All segments emitted before the Nth assistant event share turn "
            "index N. Used as the eviction-cycle boundary during replay."
        )
    )
    event_index: int = Field(
        description=(
            "Zero-based position in the raw event stream. Strictly monotonic "
            "across the whole trace; preserves intra-turn ordering when "
            "multiple segments share a turn_index."
        )
    )
    timestamp: float
    kind: TraceSegmentKind
    content: str
    token_count: int

    # Tool-call bookkeeping. Both present for tool_use; tool_use_id only for
    # tool_result so the reference graph can stitch pairs back together.
    tool_name: str | None = None
    tool_use_id: str | None = None

    # Optional hint extracted from tool_use inputs that reference a file path.
    # Used by the reference graph to detect "same file re-read" edges.
    source_file: str | None = None

    # Provenance back to the raw event. Helpful for debugging and for
    # building the lenient reference graph without losing information.
    raw_event_uuid: str | None = None
    parent_event_uuid: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    """A full recorded agent session, normalized."""

    trace_id: str
    source_path: str
    project: str
    cwd: str | None = None
    model: str | None = None
    cli_version: str | None = None
    git_branch: str | None = None
    segments: list[TraceSegment]

    @property
    def num_turns(self) -> int:
        if not self.segments:
            return 0
        return max(s.turn_index for s in self.segments) + 1

    @property
    def total_tokens(self) -> int:
        return sum(s.token_count for s in self.segments)
