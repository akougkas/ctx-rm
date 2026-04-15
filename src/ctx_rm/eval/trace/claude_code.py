"""Loader for Claude Code JSONL session transcripts.

Claude Code writes every session to `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`.
Each line is a single JSON event. Subagent sessions live under
`<uuid>/subagents/agent-<id>.jsonl` and use the same schema. This module only
parses the raw JSONL; the normalization into canonical TraceSegments is done
by `ctx_rm.eval.trace.normalize`.

The loader is deliberately lenient about unknown or partial events: real
session files contain `permission-mode`, `file-history-snapshot`, `progress`,
`attachment`, and `system` events alongside the user/assistant turns, and
the schema has changed across CLI versions. We skip what we don't understand
rather than failing, but we keep counts so the caller can see what was
dropped.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RawEvent:
    """One JSON line from a Claude Code transcript.

    We carry the raw dict through because the normalizer needs provider-
    specific fields (`message.content`, `message.model`, tool block shapes)
    that don't belong in the canonical TraceSegment schema.
    """

    index: int
    type: str
    raw: dict

    @property
    def uuid(self) -> str | None:
        return self.raw.get("uuid")

    @property
    def parent_uuid(self) -> str | None:
        return self.raw.get("parentUuid")

    @property
    def timestamp_iso(self) -> str | None:
        return self.raw.get("timestamp")


@dataclass
class LoadedTranscript:
    """Raw load result before normalization.

    Exposes metadata extracted from the first few events plus the event list
    and a histogram of skipped event types so failures during normalization
    are easy to diagnose.
    """

    path: str
    session_id: str
    cwd: str | None
    model: str | None
    cli_version: str | None
    git_branch: str | None
    events: list[RawEvent]
    skipped_types: dict[str, int] = field(default_factory=dict)

    @property
    def num_events(self) -> int:
        return len(self.events)


# Event types we currently ingest. Everything else goes in skipped_types.
_SUPPORTED_TYPES = frozenset({"user", "assistant", "system", "attachment"})


def load_transcript(path: str | Path) -> LoadedTranscript:
    """Read one JSONL file into a LoadedTranscript.

    Any line that cannot be JSON-parsed is silently skipped; Claude Code
    occasionally writes partial lines on crash and we'd rather lose one
    event than fail the whole corpus scan.
    """
    p = Path(path)
    events: list[RawEvent] = []
    skipped: dict[str, int] = {}

    session_id: str | None = None
    cwd: str | None = None
    model: str | None = None
    cli_version: str | None = None
    git_branch: str | None = None

    idx = 0
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                skipped["_malformed_json"] = skipped.get("_malformed_json", 0) + 1
                continue

            etype = raw.get("type", "_unknown")
            session_id = session_id or raw.get("sessionId")
            cwd = cwd or raw.get("cwd")
            cli_version = cli_version or raw.get("version")
            git_branch = git_branch or raw.get("gitBranch")

            # Model hides inside assistant.message.model — capture once so
            # downstream reports can filter by model without touching the
            # raw events.
            if model is None and etype == "assistant":
                msg = raw.get("message") or {}
                if isinstance(msg, dict):
                    model = msg.get("model")

            if etype not in _SUPPORTED_TYPES:
                skipped[etype] = skipped.get(etype, 0) + 1
                continue

            events.append(RawEvent(index=idx, type=etype, raw=raw))
            idx += 1

    if session_id is None:
        # Fall back to filename stem so every transcript has an id.
        session_id = p.stem

    return LoadedTranscript(
        path=str(p),
        session_id=session_id,
        cwd=cwd,
        model=model,
        cli_version=cli_version,
        git_branch=git_branch,
        events=events,
        skipped_types=skipped,
    )


def discover_transcripts(root: str | Path) -> list[Path]:
    """Walk a `~/.claude/projects/<project>/` subtree and return every .jsonl.

    Handles both main-session files (`<project>/<uuid>.jsonl`) and subagent
    files (`<project>/<uuid>/subagents/agent-*.jsonl`). awoc's top-level
    session files don't always exist — all traces live under subagents — so
    we simply enumerate everything.
    """
    root_path = Path(root)
    if not root_path.exists():
        return []
    result: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root_path):
        for name in filenames:
            if name.endswith(".jsonl"):
                result.append(Path(dirpath) / name)
    result.sort()
    return result
