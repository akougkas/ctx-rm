"""Tests for OllamaScorer — all mocked, no real Ollama needed."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ctx_rm.core.segment import Segment, SegmentRole
from ctx_rm.integrations.ollama_scorer import (
    SCORING_SYSTEM_PROMPT,
    OllamaScorer,
    RelevanceScore,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_mock_client(
    models: list[str] | None = None, score: float = 0.75, reasoning: str = "relevant"
) -> AsyncMock:
    """Create a mock AsyncClient with configurable model list and chat response."""
    client = AsyncMock()

    # Mock list() for model discovery
    model_mocks = []
    for name in models or ["llama3.2:3b"]:
        m = MagicMock()
        m.model = name
        model_mocks.append(m)
    list_resp = MagicMock()
    list_resp.models = model_mocks
    client.list.return_value = list_resp

    # Mock chat() for scoring
    chat_resp = MagicMock()
    chat_resp.message.content = f'{{"score": {score}, "reasoning": "{reasoning}"}}'
    client.chat.return_value = chat_resp

    return client


@pytest.fixture
def mock_client() -> AsyncMock:
    return _make_mock_client()


def _make_segments(n: int = 3) -> list[Segment]:
    """Create n segments with distinct content."""
    return [
        Segment(content=f"segment content {i}", role=SegmentRole.TOOL)
        for i in range(n)
    ]


@pytest.fixture
def segments() -> list[Segment]:
    return _make_segments()


def _make_scorer(client: AsyncMock, **kwargs) -> OllamaScorer:
    """Create OllamaScorer with mocked client injected."""
    with patch("ollama.AsyncClient", return_value=client):
        scorer = OllamaScorer(**kwargs)
    # Ensure the client is our mock
    scorer._client = client
    return scorer


# ── LLMS-01: Calls Ollama and returns score ───────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_calls_ollama_for_scoring(mock_client: AsyncMock) -> None:
    """LLMS-01: OllamaScorer calls Ollama chat and sets relevance_score."""
    scorer = _make_scorer(mock_client, task_goal="Fix auth bug")
    segs = _make_segments(1)

    await scorer._async_score_batch(segs, [])

    assert mock_client.chat.called
    assert segs[0].relevance_score == 0.75


# ── LLMS-02: Dynamic model discovery ─────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_discovers_model_dynamically(
    mock_client: AsyncMock,
) -> None:
    """LLMS-02: With model=None, scorer discovers model via client.list()."""
    scorer = _make_scorer(mock_client, model=None, task_goal="test")
    segs = _make_segments(1)

    await scorer._async_score_batch(segs, [])

    mock_client.list.assert_called_once()
    # Chat should use the discovered model
    chat_call = mock_client.chat.call_args
    assert chat_call.kwargs["model"] == "llama3.2:3b"


@pytest.mark.asyncio
async def test_ollama_scorer_prefers_specified_model() -> None:
    """LLMS-02b: When preferred model is in list, use it instead of first."""
    client = _make_mock_client(models=["llama3.2:3b", "qwen2.5:7b"])
    scorer = _make_scorer(client, model="qwen2.5:7b", task_goal="test")
    segs = _make_segments(1)

    await scorer._async_score_batch(segs, [])

    chat_call = client.chat.call_args
    assert chat_call.kwargs["model"] == "qwen2.5:7b"


# ── LLMS-03: Task goal + content in prompt ────────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_sends_task_goal_and_content(
    mock_client: AsyncMock,
) -> None:
    """LLMS-03: System prompt + user message contain task goal and segment content."""
    scorer = _make_scorer(mock_client, task_goal="Implement caching")
    segs = [Segment(content="Redis client setup", role=SegmentRole.TOOL)]

    await scorer._async_score_batch(segs, [])

    chat_call = mock_client.chat.call_args
    messages = chat_call.kwargs["messages"]

    # System message is the scoring prompt
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SCORING_SYSTEM_PROMPT

    # User message contains task goal and segment content
    user_msg = messages[1]["content"]
    assert "Implement caching" in user_msg
    assert "Redis client setup" in user_msg


# ── LLMS-04: Score caching ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_caches_scores(mock_client: AsyncMock) -> None:
    """LLMS-04: Same (content, task_goal) pair uses cached score on second call."""
    scorer = _make_scorer(mock_client, task_goal="bar")
    seg1 = Segment(content="foo", role=SegmentRole.TOOL)
    seg2 = Segment(content="foo", role=SegmentRole.TOOL)

    await scorer._async_score_batch([seg1], [])
    await scorer._async_score_batch([seg2], [])

    assert mock_client.chat.call_count == 1
    assert seg2.relevance_score == 0.75


@pytest.mark.asyncio
async def test_ollama_scorer_cache_miss_on_different_task(
    mock_client: AsyncMock,
) -> None:
    """LLMS-04b: Different task_goal causes cache miss for same content."""
    scorer_a = _make_scorer(mock_client, task_goal="A")
    scorer_b = _make_scorer(mock_client, task_goal="B")
    # Share cache between scorers for this test
    scorer_b._cache = scorer_a._cache

    seg1 = Segment(content="same content", role=SegmentRole.TOOL)
    seg2 = Segment(content="same content", role=SegmentRole.TOOL)

    await scorer_a._async_score_batch([seg1], [])
    await scorer_b._async_score_batch([seg2], [])

    assert mock_client.chat.call_count == 2


# ── LLMS-05: Batch concurrency ───────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_batch_concurrency(mock_client: AsyncMock) -> None:
    """LLMS-05: Batch scoring processes all segments with bounded concurrency."""
    scorer = _make_scorer(mock_client, max_concurrent=2, task_goal="test")
    segs = _make_segments(5)

    await scorer._async_score_batch(segs, [])

    assert all(s.relevance_score == 0.75 for s in segs)
    assert mock_client.chat.call_count == 5


# ── LLMS-06: Fallback on errors ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_fallback_on_connection_error() -> None:
    """LLMS-06: Connection error triggers full fallback to HeuristicScorer."""
    client = _make_mock_client()
    client.list.side_effect = ConnectionError("refused")
    scorer = _make_scorer(client, task_goal="test")
    segs = _make_segments(2)

    # _async_score_batch will raise due to discover_model failing.
    # score_batch catches and falls back.
    scorer.score_batch(segs, [])

    # HeuristicScorer sets composite_score (not just relevance_score)
    assert all(s.composite_score is not None for s in segs)


@pytest.mark.asyncio
async def test_ollama_scorer_fallback_on_chat_error() -> None:
    """LLMS-06b: Per-segment chat errors cause fallback for those segments."""
    client = _make_mock_client()
    client.chat.side_effect = Exception("model error")
    scorer = _make_scorer(client, task_goal="test")
    segs = _make_segments(2)

    await scorer._async_score_batch(segs, [])

    # Failed segments get filled by fallback (HeuristicScorer sets composite_score)
    assert all(s.composite_score is not None for s in segs)


# ── LLMS-07: Config defaults ─────────────────────────────────────────


def test_ollama_scorer_config_defaults() -> None:
    """LLMS-07: Default config uses heuristic scorer, not ollama."""
    from ctx_rm.config import CtxRmConfig

    config = CtxRmConfig()
    assert config.scorer == "heuristic"
    assert config.ollama_host == "http://localhost:11434"
    assert config.ollama_model is None
    assert config.ollama_max_concurrent == 4


# ── Edge: Import guard ────────────────────────────────────────────────


def test_ollama_scorer_import_error_without_package() -> None:
    """Without ollama installed, OllamaScorer raises ImportError with instructions."""
    with patch.dict("sys.modules", {"ollama": None}), pytest.raises(
        ImportError, match=r"ctx-rm\[ollama\]"
    ):
        OllamaScorer()


# ── Edge: Out-of-range score clamping ─────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_handles_out_of_range_score() -> None:
    """Out-of-range score from LLM is clamped or handled gracefully."""
    client = _make_mock_client()
    # Return score > 1.0 — Pydantic will reject, then raw parse + clamp
    chat_resp = MagicMock()
    chat_resp.message.content = '{"score": 1.5, "reasoning": "very relevant"}'
    client.chat.return_value = chat_resp

    scorer = _make_scorer(client, task_goal="test")
    segs = _make_segments(1)

    await scorer._async_score_batch(segs, [])

    # Score should be clamped to 1.0 via raw parse fallback
    assert segs[0].relevance_score == 1.0


# ── Edge: RelevanceScore model ────────────────────────────────────────


def test_relevance_score_valid() -> None:
    """RelevanceScore accepts valid score in [0, 1]."""
    rs = RelevanceScore(score=0.5, reasoning="test")
    assert rs.score == 0.5
    assert rs.reasoning == "test"


def test_relevance_score_rejects_out_of_range() -> None:
    """RelevanceScore rejects score outside [0, 1]."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RelevanceScore(score=1.5)

    with pytest.raises(ValidationError):
        RelevanceScore(score=-0.1)


# ── Edge: No models available ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_scorer_no_models_available() -> None:
    """RuntimeError when Ollama has no models; score_batch falls back."""
    client = _make_mock_client()
    list_resp = MagicMock()
    list_resp.models = []
    client.list.return_value = list_resp

    scorer = _make_scorer(client, task_goal="test")
    segs = _make_segments(1)

    # _async_score_batch raises RuntimeError, score_batch catches and falls back
    scorer.score_batch(segs, [])
    assert segs[0].composite_score is not None
