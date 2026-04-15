"""Reference graph: which later segments reference an earlier segment?

This is the oracle labeler. It takes a normalized Trace and produces, for
every segment X, the set of later segments that reference X's content. From
that we derive the binary label `referenced_after(X, turn) -> bool` that
the L1 metrics and OraclePolicy use as ground truth.

Two strictness modes
--------------------

**Strict.** Reference edges require high-precision evidence:

1. **File re-read.** X is a tool_use or tool_result associated with a file
   path P. Y is a later tool_use whose `source_file == P`. We consider both
   sides because Y re-reading P implies the agent wanted P's content again —
   whether X is the prior read (tool_use) or its result (tool_result).
2. **Tool result reuse.** X is a tool_result. Y is a later TOOL_USE or
   ASSISTANT_TEXT block whose content contains a substring of X of length
   ≥ `MIN_EXACT_QUOTE_CHARS` that is not a stopword phrase. This catches
   cases where the agent quotes a value it learned from a tool.

**Lenient.** Adds one more rule:

3. **Distinctive n-gram overlap.** X and Y share a 5-token non-stopword
   n-gram. This catches paraphrases and refactor-style reuse where the agent
   uses the same identifier names as the earlier segment without quoting
   verbatim. Higher recall, lower precision — we report metrics under both
   modes so the paper can show the bracket.

Design notes
------------

- The graph is computed once per trace in O(N * K) where K is the average
  number of candidate reference indices per segment. For our traces
  (hundreds of segments), K is small because we index shingles/paths and
  only compare segments whose keys overlap.
- System, assistant_thinking, and attachment segments are never treated as
  *referencing* anything (they don't produce new queries) but can be
  *referenced* by later segments. They're passive content.
- Self-references are excluded. An assistant text block quoting itself does
  not count.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from ctx_rm.eval.trace.schema import Trace, TraceSegment, TraceSegmentKind

# Tunables. Centralized so the paper can report the exact values used.
MIN_EXACT_QUOTE_CHARS = 20
NGRAM_SIZE = 5
MIN_DISTINCTIVE_TOKEN_LEN = 3

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "have",
        "has",
        "are",
        "was",
        "were",
        "will",
        "not",
        "but",
        "all",
        "any",
        "can",
        "you",
        "your",
        "our",
        "out",
        "one",
        "two",
        "some",
        "more",
        "most",
        "each",
        "than",
        "then",
        "them",
        "there",
        "here",
        "what",
        "when",
        "which",
        "who",
        "why",
        "how",
        "been",
        "being",
        "about",
        "also",
        "just",
        "only",
        "very",
        "such",
        "these",
        "those",
        "they",
        "its",
        "it's",
        "isn't",
        "don't",
        "doesn't",
        "like",
        "use",
        "used",
        "using",
        "uses",
        "get",
        "got",
        "see",
        "make",
        "made",
    }
)


class ReferenceMode(StrEnum):
    STRICT = "strict"
    LENIENT = "lenient"


class ReferenceEdgeKind(StrEnum):
    FILE_REREAD = "file_reread"
    EXACT_QUOTE = "exact_quote"
    NGRAM_OVERLAP = "ngram_overlap"


@dataclass(frozen=True)
class ReferenceEdge:
    """Directed edge meaning `target` references `source`.

    `source.event_index < target.event_index` is an invariant. We carry the
    kind for debugging and for per-category precision analysis in the paper.
    """

    source_seg_id: str
    target_seg_id: str
    kind: ReferenceEdgeKind


class ReferenceGraph:
    """Pre-computed oracle labels for one trace.

    Use `build(trace, mode)` to construct. Query with `is_referenced_after`
    to implement the oracle policy and the retention metric. The internal
    representation is a set of (source, target) pairs plus per-segment
    outgoing adjacency lists.
    """

    def __init__(self, trace: Trace, mode: ReferenceMode) -> None:
        self.trace = trace
        self.mode = mode
        self._out: dict[str, list[ReferenceEdge]] = defaultdict(list)
        self._edges: list[ReferenceEdge] = []
        # Earliest future reference turn, by source seg_id. Used for the
        # per-segment "is this segment needed again after turn T?" check.
        self._earliest_future_turn: dict[str, int] = {}

    @classmethod
    def build(cls, trace: Trace, mode: ReferenceMode = ReferenceMode.STRICT) -> ReferenceGraph:
        graph = cls(trace, mode)
        graph._populate()
        return graph

    def _populate(self) -> None:
        self._rule_file_reread()
        self._rule_exact_quote()
        if self.mode == ReferenceMode.LENIENT:
            self._rule_ngram_overlap()

    def _rule_file_reread(self) -> None:
        """Rule: later tool_use of path P references earlier segments touching P."""
        segs = self.trace.segments

        # Index 1: file-path → indices of segments that touch that path.
        #   - tool_use with source_file=P produces/reads P
        #   - tool_result carries the last-read content for whichever tool
        #     used a path; we tag it with the tool's source_file at lookup
        #     time rather than copying it into the TraceSegment.
        path_index: dict[str, list[int]] = defaultdict(list)
        tool_use_path_by_id: dict[str, str] = {}
        for i, s in enumerate(segs):
            if s.kind == TraceSegmentKind.TOOL_USE and s.source_file:
                path_index[s.source_file].append(i)
                if s.tool_use_id:
                    tool_use_path_by_id[s.tool_use_id] = s.source_file

        # Propagate path labels into tool_results by their tool_use_id.
        result_path: dict[int, str] = {}
        for i, s in enumerate(segs):
            if s.kind == TraceSegmentKind.TOOL_RESULT and s.tool_use_id:
                p = tool_use_path_by_id.get(s.tool_use_id)
                if p:
                    path_index[p].append(i)
                    result_path[i] = p

        # Rule 1: file_reread. For each later tool_use with source_file=P,
        # add edges from all earlier path-tagged segments to that tool_use.
        for i, s in enumerate(segs):
            if s.kind == TraceSegmentKind.TOOL_USE and s.source_file:
                for j in path_index.get(s.source_file, []):
                    if j < i:
                        src = segs[j]
                        if src.seg_id == s.seg_id:
                            continue
                        self._add_edge(src, s, ReferenceEdgeKind.FILE_REREAD)

    def _rule_exact_quote(self) -> None:
        """Rule: later tool_use/assistant_text quotes a ≥20-char run from an earlier tool_result."""
        segs = self.trace.segments

        # Rule 2: exact_quote. Build a lookup of long tokens from each
        # tool_result, then scan later tool_use / assistant_text bodies
        # for substring matches. We cap the quote length so the check
        # stays O(N * avg_result_length).
        # To bound cost, only use the first ~4 KB of each source segment.
        result_excerpts: list[tuple[int, str]] = []
        for i, s in enumerate(segs):
            if s.kind == TraceSegmentKind.TOOL_RESULT and s.content:
                excerpt = s.content[:4096]
                result_excerpts.append((i, excerpt))

        for i, s in enumerate(segs):
            if s.kind not in (
                TraceSegmentKind.TOOL_USE,
                TraceSegmentKind.ASSISTANT_TEXT,
            ):
                continue
            if not s.content:
                continue
            target_body = s.content
            for j, excerpt in result_excerpts:
                if j >= i:
                    break
                # Heuristic: look for an identifier-like token from the
                # result that appears verbatim in the target. We avoid a
                # full substring sweep by scanning words of length ≥ 8
                # from the excerpt.
                hit = False
                for match in _TOKEN_RE.finditer(excerpt):
                    tok = match.group(0)
                    if len(tok) >= 8 and tok.lower() not in _STOPWORDS and tok in target_body:
                        hit = True
                        break
                if hit:
                    # Confirm with a longer substring test to reduce noise.
                    # Any 20+ char run from the excerpt that appears in the
                    # target counts as a direct quote.
                    for start in range(0, len(excerpt) - MIN_EXACT_QUOTE_CHARS, 64):
                        chunk = excerpt[start : start + MIN_EXACT_QUOTE_CHARS]
                        if chunk and chunk in target_body:
                            src = segs[j]
                            if src.seg_id != s.seg_id:
                                self._add_edge(src, s, ReferenceEdgeKind.EXACT_QUOTE)
                            break

    def _rule_ngram_overlap(self) -> None:
        """Rule: lenient-only paraphrase catch via shared 5-token distinctive shingles."""
        segs = self.trace.segments

        # Rule 3: ngram_overlap (lenient only). Build 5-token shingle sets
        # for every content-bearing segment and intersect pairwise with a
        # prefix index so we only compare plausible matches.
        shingles: dict[int, set[tuple[str, ...]]] = {}
        prefix_index: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for i, s in enumerate(segs):
            if s.kind in (
                TraceSegmentKind.SYSTEM,
                TraceSegmentKind.ASSISTANT_THINKING,
                TraceSegmentKind.ATTACHMENT,
            ):
                continue
            if not s.content:
                continue
            sh = _compute_shingles(s.content)
            if not sh:
                continue
            shingles[i] = sh
            # Index by first 2 tokens of each shingle for quick narrowing.
            for tup in sh:
                prefix_index[tup[:2]].append(i)

        seen_pairs: set[tuple[int, int]] = set()
        for i, target_sh in shingles.items():
            candidates: set[int] = set()
            for tup in target_sh:
                for j in prefix_index.get(tup[:2], ()):
                    if j < i:
                        candidates.add(j)
            for j in candidates:
                if (j, i) in seen_pairs:
                    continue
                seen_pairs.add((j, i))
                if shingles[j] & target_sh:
                    src = segs[j]
                    tgt = segs[i]
                    if src.seg_id != tgt.seg_id:
                        self._add_edge(src, tgt, ReferenceEdgeKind.NGRAM_OVERLAP)

    def _add_edge(
        self,
        source: TraceSegment,
        target: TraceSegment,
        kind: ReferenceEdgeKind,
    ) -> None:
        if source.event_index >= target.event_index:
            return
        edge = ReferenceEdge(
            source_seg_id=source.seg_id,
            target_seg_id=target.seg_id,
            kind=kind,
        )
        self._edges.append(edge)
        self._out[source.seg_id].append(edge)
        prior = self._earliest_future_turn.get(source.seg_id)
        if prior is None or target.turn_index < prior:
            self._earliest_future_turn[source.seg_id] = target.turn_index

    # ── Query API ───────────────────────────────────────────────────────

    @property
    def edges(self) -> list[ReferenceEdge]:
        return list(self._edges)

    @property
    def num_edges(self) -> int:
        return len(self._edges)

    def referenced_seg_ids(self) -> set[str]:
        """Segments that are referenced by at least one later segment."""
        return set(self._out.keys())

    def is_referenced_after(self, seg_id: str, turn: int) -> bool:
        """True iff some later segment at turn > `turn` references `seg_id`."""
        earliest = self._earliest_future_turn.get(seg_id)
        return earliest is not None and earliest > turn

    def earliest_future_turn(self, seg_id: str) -> int | None:
        """Smallest target.turn_index among edges whose source is seg_id.

        Returns None when the segment is never referenced. Callers should
        treat None as "safe to evict" under a future-only oracle."""
        return self._earliest_future_turn.get(seg_id)

    def outgoing(self, seg_id: str) -> list[ReferenceEdge]:
        return list(self._out.get(seg_id, ()))


def _compute_shingles(content: str) -> set[tuple[str, ...]]:
    """Distinctive 5-token shingle set, stopwords removed, min token length."""
    tokens = [
        t.lower()
        for t in _TOKEN_RE.findall(content)
        if len(t) >= MIN_DISTINCTIVE_TOKEN_LEN and t.lower() not in _STOPWORDS
    ]
    if len(tokens) < NGRAM_SIZE:
        return set()
    return {tuple(tokens[i : i + NGRAM_SIZE]) for i in range(len(tokens) - NGRAM_SIZE + 1)}
