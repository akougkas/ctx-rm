"""OllamaScorer: LLM-based segment relevance scoring via local Ollama.

Requires: pip install ctx-rm[ollama]
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field, ValidationError

from ctx_rm.core.scorer import HeuristicScorer, Scorer

if TYPE_CHECKING:
    from ctx_rm.core.segment import Segment

logger = structlog.get_logger()

SCORING_SYSTEM_PROMPT = """\
You are a relevance scorer for an LLM context management system.
Given a task description and a context segment, score how relevant
the segment is to completing the task.

Score from 0.0 to 1.0:
- 0.0: Completely irrelevant to the task
- 0.2: Tangentially related but not useful
- 0.5: Somewhat relevant, provides background
- 0.8: Highly relevant, directly useful
- 1.0: Critical — directly needed to complete the task

Use the full range. Provide your reasoning, then the score."""


class RelevanceScore(BaseModel):
    """Ollama response schema for segment relevance scoring."""

    score: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class OllamaScorer(Scorer):
    """LLM-based scorer using a local Ollama instance.

    Features:
      - Dynamic model discovery via client.list()
      - Structured output via Pydantic schema + Ollama format parameter
      - MD5-keyed cache avoids redundant LLM calls
      - asyncio.Semaphore bounds concurrent requests
      - Silent fallback to HeuristicScorer on any error
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str | None = None,
        max_concurrent: int = 4,
        task_goal: str = "",
        fallback: Scorer | None = None,
    ) -> None:
        try:
            from ollama import AsyncClient
        except ImportError:
            raise ImportError(
                "ollama is required for OllamaScorer. "
                "Install with: pip install ctx-rm[ollama]"
            ) from None

        self._client = AsyncClient(host=host)
        self._model = model
        self._max_concurrent = max_concurrent
        self._task_goal = task_goal
        self._fallback = fallback or HeuristicScorer()
        self._cache: dict[tuple[str, str], float] = {}
        self._discovered_model: str | None = None

    def score_batch(
        self, candidates: list[Segment], context: list[Segment]
    ) -> None:
        """Score candidates via Ollama, falling back to heuristic on failure."""
        try:
            try:
                import anyio

                anyio.from_thread.run(self._async_score_batch, candidates, context)
            except RuntimeError:
                # No async context available, use asyncio.run directly
                asyncio.run(self._async_score_batch(candidates, context))
        except Exception as e:
            logger.debug("ollama_fallback", reason=str(e))
            self._fallback.score_batch(candidates, context)

    async def _async_score_batch(
        self, candidates: list[Segment], context: list[Segment]
    ) -> None:
        """Async batch scoring with semaphore-bounded concurrency."""
        if self._discovered_model is None:
            await self._discover_model()

        sem = asyncio.Semaphore(self._max_concurrent)

        async def _score_one(seg: Segment) -> None:
            async with sem:
                cache_key = self._cache_key(seg.content, self._task_goal)
                if cache_key in self._cache:
                    seg.relevance_score = self._cache[cache_key]
                    return

                try:
                    response = await self._client.chat(
                        model=self._discovered_model,
                        messages=[
                            {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    f"Task: {self._task_goal}\n\n"
                                    f"Segment:\n{seg.content}"
                                ),
                            },
                        ],
                        format=RelevanceScore.model_json_schema(),
                        options={"temperature": 0},
                    )
                    result = RelevanceScore.model_validate_json(
                        response.message.content
                    )
                    score = max(0.0, min(1.0, result.score))
                    seg.relevance_score = score
                    self._cache[cache_key] = score
                except ValidationError:
                    # LLM returned out-of-range or malformed JSON; try raw parse
                    try:
                        import json

                        raw = json.loads(response.message.content)
                        score = max(0.0, min(1.0, float(raw.get("score", 0.5))))
                        seg.relevance_score = score
                        self._cache[cache_key] = score
                    except Exception:
                        logger.debug(
                            "ollama_score_error",
                            seg_id=seg.seg_id,
                            error="validation_and_parse_failed",
                        )
                        seg.relevance_score = None
                except Exception as e:
                    logger.debug(
                        "ollama_score_error", seg_id=seg.seg_id, error=str(e)
                    )
                    seg.relevance_score = None

        await asyncio.gather(*[_score_one(seg) for seg in candidates])

        # Fill in any failed segments via fallback
        failed = [seg for seg in candidates if seg.relevance_score is None]
        if failed:
            self._fallback.score_batch(failed, context)

    async def _discover_model(self) -> None:
        """Discover available models from Ollama, prefer user's choice."""
        response = await self._client.list()
        available = [m.model for m in response.models]
        if not available:
            msg = "No Ollama models available"
            raise RuntimeError(msg)
        if self._model and self._model in available:
            self._discovered_model = self._model
        else:
            self._discovered_model = available[0]
        logger.info("ollama_model_discovered", model=self._discovered_model)

    @staticmethod
    def _cache_key(content: str, task_goal: str) -> tuple[str, str]:
        """Compute cache key from content and task goal hashes."""
        seg_hash = hashlib.md5(content.encode()).hexdigest()
        task_hash = hashlib.md5(task_goal.encode()).hexdigest()
        return (seg_hash, task_hash)
