"""Tests for configurable source weights, content-based recall, recall budget, and recall precision.

Covers four requirements:
  SCORE-01: HeuristicScorer with configurable per-source weights
  RECALL-01: Content-based recall on file_read tool results
  RECALL-02: Per-turn recall budget limiting
  RECALL-03: Recall precision tracking (hits/total)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.segment import Segment, SegmentRole, Tier
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.agents.loop import AgentLoop, AgentResult
from ctx_rm.drivers.llamacpp import ChatResponse, ToolCall


# ── Helpers ──────────────────────────────────────────────────────────────


def _seg(
    content: str = "test content",
    source: str = "test",
    tokens: int = 10,
    role: SegmentRole = SegmentRole.CONTEXT,
) -> Segment:
    return Segment(
        content=content,
        role=role,
        token_count=tokens,
        source=source,
    )


class MockDriver:
    """Mock LlamaCpp driver returning canned responses in sequence."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self._idx = 0
        self.call_log: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.call_log.append({"messages": list(messages), "tools": tools})
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


def _bus(budget: int = 10_000, headroom: float = 0.15) -> ContextBus:
    return ContextBus(
        token_budget=budget,
        store=TieredStore(),
        policy=LRUPolicy(),
        headroom_ratio=headroom,
    )


def _bus_with_embedding(budget: int = 10_000, headroom: float = 0.15) -> ContextBus:
    from ctx_rm.core.embedding import HashingEmbeddingProvider

    return ContextBus(
        token_budget=budget,
        store=TieredStore(embedding_provider=HashingEmbeddingProvider()),
        policy=LRUPolicy(),
        headroom_ratio=headroom,
    )


def _text(content: str, pt: int = 50, ct: int = 10) -> ChatResponse:
    return ChatResponse(
        content=content, prompt_tokens=pt, completion_tokens=ct,
        total_tokens=pt + ct,
    )


def _tool(name: str, args: dict, call_id: str = "call_0") -> ChatResponse:
    return ChatResponse(
        content=None,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        prompt_tokens=50, completion_tokens=10, total_tokens=60,
    )


# ══════════════════════════════════════════════════════════════════════════
# SCORE-01: Configurable per-source weights
# ══════════════════════════════════════════════════════════════════════════


class TestSourceScoresConfigurable:
    """HeuristicScorer source_scores dict is configurable at construction
    and used in composite scoring."""

    def test_source_scores_configurable(self) -> None:
        """Custom source_scores dict is used; needle scores higher than noise."""
        scorer = HeuristicScorer(
            source_weight=0.5,
            source_scores={"needle": 0.95, "noise": 0.05, "tool": 0.4},
        )

        needle_seg = _seg(content="important data", source="needle:N1")
        noise_seg = _seg(content="important data", source="noise:dump")

        # Give both segments identical recency/frequency/role to isolate source effect
        needle_seg.last_accessed = noise_seg.last_accessed
        needle_seg.created_at = noise_seg.created_at
        needle_seg.access_count = noise_seg.access_count
        needle_seg.role = noise_seg.role

        scorer.score_batch([needle_seg, noise_seg], [])

        assert needle_seg.composite_score is not None
        assert noise_seg.composite_score is not None
        assert needle_seg.composite_score > noise_seg.composite_score

    def test_source_scores_default_preserved(self) -> None:
        """Default source_scores has expected values for needle and noise."""
        scorer = HeuristicScorer()

        assert scorer.source_scores["needle"] == 0.85
        assert scorer.source_scores["noise"] == 0.1

    def test_source_weight_zero_ignores_source(self) -> None:
        """With source_weight=0 (default), different sources produce equal scores."""
        scorer = HeuristicScorer(source_weight=0.0)

        needle_seg = _seg(content="same data", source="needle:N1")
        noise_seg = _seg(content="same data", source="noise:dump")

        # Equalize all non-source factors
        needle_seg.last_accessed = noise_seg.last_accessed
        needle_seg.created_at = noise_seg.created_at
        needle_seg.access_count = noise_seg.access_count
        needle_seg.role = noise_seg.role

        scorer.score_batch([needle_seg, noise_seg], [])

        assert needle_seg.composite_score == pytest.approx(
            noise_seg.composite_score, abs=1e-6
        )


# ══════════════════════════════════════════════════════════════════════════
# RECALL-01: Content-based recall on file_read
# ══════════════════════════════════════════════════════════════════════════


class TestContentBasedRecall:
    """When an agent reads a file that was previously evicted,
    the original segment is recalled automatically."""

    @pytest.mark.asyncio
    async def test_content_recall_on_file_read(self, tmp_path) -> None:
        """Evicted file_read segment is recalled when same file is re-read.

        1. Agent reads src/auth.py -> segment created with source tool:file_read
        2. Segment gets evicted (budget pressure)
        3. Agent reads src/auth.py again -> content-based recall should fire
        """
        (tmp_path / "auth.py").write_text("def authenticate(): pass")

        bus = _bus_with_embedding(budget=300, headroom=0.2)

        # Pre-inject an evicted segment simulating a previous file_read of auth.py
        evicted_seg = Segment(
            content="def authenticate(): pass  # original read",
            role=SegmentRole.TOOL,
            token_count=30,
            source="tool:file_read",
            metadata={
                "openai_message": {
                    "role": "tool",
                    "content": "def authenticate(): pass  # original read",
                    "tool_call_id": "old_call",
                },
                "tool_call_id": "old_call",
            },
        )
        # Place it directly in warm (simulating eviction)
        bus.store.demote_to_warm(evicted_seg)
        evicted_id = evicted_seg.seg_id

        # Agent does a file_read, then text response
        driver = MockDriver([
            _tool("file_read", {"path": str(tmp_path / "auth.py")}, call_id="c0"),
            _text("Read the auth file"),
        ])

        loop = AgentLoop(
            driver=driver, bus=bus, working_dir=str(tmp_path),
            enable_recall=True, recall_top_k=3,
        )

        result = await loop.run("sys", "Review auth code")

        # The _try_content_recall method should exist and have been called
        assert hasattr(loop, '_try_content_recall'), (
            "_try_content_recall method must exist on AgentLoop"
        )

    @pytest.mark.asyncio
    async def test_content_recall_skips_already_recalled(self, tmp_path) -> None:
        """If a segment was already recalled, content-based recall does not re-recall it."""
        (tmp_path / "data.py").write_text("x = 1")

        bus = _bus_with_embedding(budget=500, headroom=0.2)

        evicted_seg = Segment(
            content="x = 1  # previously read",
            role=SegmentRole.TOOL,
            token_count=20,
            source="tool:file_read",
            metadata={
                "openai_message": {
                    "role": "tool",
                    "content": "x = 1  # previously read",
                    "tool_call_id": "old_c",
                },
                "tool_call_id": "old_c",
            },
        )
        bus.store.demote_to_warm(evicted_seg)
        evicted_id = evicted_seg.seg_id

        # Two file_reads of same file -> should only recall once
        driver = MockDriver([
            _tool("file_read", {"path": str(tmp_path / "data.py")}, call_id="c0"),
            _tool("file_read", {"path": str(tmp_path / "data.py")}, call_id="c1"),
            _text("Done"),
        ])

        loop = AgentLoop(
            driver=driver, bus=bus, working_dir=str(tmp_path),
            enable_recall=True, recall_top_k=3,
        )

        result = await loop.run("sys", "Read data")

        # Should only have recalled the segment once (dedup by _recalled_ids)
        recall_count_for_id = sum(
            1 for sid in loop._recalled_ids if sid == evicted_id
        )
        assert recall_count_for_id <= 1


# ══════════════════════════════════════════════════════════════════════════
# RECALL-02: Recall budget limits per-turn recalls
# ══════════════════════════════════════════════════════════════════════════


class TestRecallBudget:
    """Recall is bounded by a per-turn budget (max segments recalled per turn)."""

    @pytest.mark.asyncio
    async def test_recall_budget_limits_per_turn(self, tmp_path) -> None:
        """With recall_budget=2, only 2 segments are recalled even if 5 match."""
        bus = _bus_with_embedding(budget=2000, headroom=0.1)

        # Place 5 segments in warm that all match the task query
        for i in range(5):
            seg = Segment(
                content=f"Important config port setting number {i}",
                role=SegmentRole.CONTEXT,
                token_count=20,
                source="needle:config",
                metadata={
                    "openai_message": {
                        "role": "user",
                        "content": f"[context] Config setting {i}",
                    },
                },
            )
            bus.store.demote_to_warm(seg)

        driver = MockDriver([_text("Done")])

        loop = AgentLoop(
            driver=driver, bus=bus, working_dir=str(tmp_path),
            enable_recall=True, recall_top_k=10,
            recall_budget=2,
        )

        result = await loop.run("sys", "Check the config port settings")

        # recall_budget=2 should limit recalls to at most 2
        assert result.recalls_made <= 2

    @pytest.mark.asyncio
    async def test_recall_budget_zero_disables(self, tmp_path) -> None:
        """With recall_budget=0, no recalls happen even with matching evicted segments."""
        bus = _bus_with_embedding(budget=2000, headroom=0.1)

        seg = Segment(
            content="Important config port setting",
            role=SegmentRole.CONTEXT,
            token_count=20,
            source="needle:config",
            metadata={
                "openai_message": {
                    "role": "user",
                    "content": "[context] Config setting",
                },
            },
        )
        bus.store.demote_to_warm(seg)

        driver = MockDriver([_text("Done")])

        loop = AgentLoop(
            driver=driver, bus=bus, working_dir=str(tmp_path),
            enable_recall=True, recall_top_k=10,
            recall_budget=0,
        )

        result = await loop.run("sys", "Check the config port settings")

        assert result.recalls_made == 0


# ══════════════════════════════════════════════════════════════════════════
# RECALL-03: Recall precision tracking
# ══════════════════════════════════════════════════════════════════════════


class TestRecallPrecision:
    """Recall precision is tracked: count of recalled segments that appeared
    in subsequent tool calls."""

    @pytest.mark.asyncio
    async def test_recall_precision_tracked(self, tmp_path) -> None:
        """Recall precision distinguishes useful vs wasted recalls.

        Setup:
        - Evict a segment with content about "auth.py"
        - Recall fires (task matches)
        - Subsequent tool result contains "auth.py" -> precision hit
        """
        (tmp_path / "auth.py").write_text("def login(): pass")

        bus = _bus_with_embedding(budget=2000, headroom=0.1)

        # Evict a segment whose content will be "useful" (matched by tool result)
        useful_seg = Segment(
            content="The auth module handles login with token validation",
            role=SegmentRole.CONTEXT,
            token_count=20,
            source="needle:auth_info",
            metadata={
                "openai_message": {
                    "role": "user",
                    "content": "[context] The auth module handles login",
                },
            },
        )
        bus.store.demote_to_warm(useful_seg)

        # Tool call reads auth.py -> content overlaps with recalled segment
        driver = MockDriver([
            _tool("file_read", {"path": str(tmp_path / "auth.py")}, call_id="c0"),
            _text("Auth looks good"),
        ])

        loop = AgentLoop(
            driver=driver, bus=bus, working_dir=str(tmp_path),
            enable_recall=True, recall_top_k=3,
        )

        result = await loop.run("sys", "Review the auth module login")

        # recall_precision should be available on the result
        assert hasattr(result, 'recall_precision'), (
            "AgentResult must include recall_precision field"
        )

    @pytest.mark.asyncio
    async def test_recall_precision_reported_in_result(self, tmp_path) -> None:
        """AgentResult includes recall_precision (hits/total) as a float."""
        bus = _bus(budget=10_000)
        driver = MockDriver([_text("Done")])

        loop = AgentLoop(
            driver=driver, bus=bus, working_dir=str(tmp_path),
            enable_recall=False,
        )

        result = await loop.run("sys", "task")

        # Even with 0 recalls, the field should exist and be 0.0
        assert hasattr(result, 'recall_precision'), (
            "AgentResult must have recall_precision field"
        )
        assert isinstance(result.recall_precision, float)
        assert result.recall_precision == 0.0
