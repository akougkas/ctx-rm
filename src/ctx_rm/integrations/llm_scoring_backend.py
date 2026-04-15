"""Reusable LLM-backed scoring helpers for SequentialScorer."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import structlog

logger = structlog.get_logger()

_REQUIRED_KEYS = frozenset(
    {"relevance_score", "staleness_score", "redundancy_score", "composite_score"}
)

_SCORING_PROMPT = """\
You are a relevance scorer for an LLM context management system.
Given a task description, a summary of retained context, and a candidate
segment, return JSON with exactly:

  relevance_score   float [0,1]
  staleness_score   float [0,1]
  redundancy_score  float [0,1]
  composite_score   float [0,1]

Return only JSON.

Task: {task_goal}

Retained context summary:
{retained_summary}

Candidate segment:
{segment_content}
"""


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _parse_score_json(raw: str) -> dict[str, float] | None:
    """Parse and validate score JSON from model output."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None
    if not _REQUIRED_KEYS.issubset(data):
        return None

    result: dict[str, float] = {}
    for key in _REQUIRED_KEYS:
        value = data[key]
        if not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                return None
        result[key] = _clamp(float(value))
    return result


def make_ollama_scoring_fn(
    host: str = "http://localhost:11434",
    model: str = "llama3.2:3b",
) -> Callable[[str, str, str], dict[str, float] | None]:
    """Create a scoring callable backed by Ollama's ``/api/generate``."""

    def _score(
        segment_content: str,
        retained_summary: str,
        task_goal: str,
    ) -> dict[str, float] | None:
        import urllib.error
        import urllib.request

        payload = json.dumps({
            "model": model,
            "prompt": _SCORING_PROMPT.format(
                task_goal=task_goal,
                retained_summary=retained_summary or "(empty)",
                segment_content=segment_content[:2000],
            ),
            "stream": False,
            "options": {"temperature": 0},
        }).encode()

        req = urllib.request.Request(
            f"{host.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            logger.debug("llm_backend_request_failed", error=str(exc))
            return None

        raw_response = body.get("response", "")
        parsed = _parse_score_json(raw_response)
        if parsed is None:
            logger.debug("llm_backend_parse_failed", raw=str(raw_response)[:200])
        return parsed

    return _score


def make_generic_scoring_fn(
    fn: Callable[[str, str, str], str],
) -> Callable[[str, str, str], dict[str, float] | None]:
    """Wrap a raw-text backend callable into validated score dict output."""

    def _score(
        segment_content: str,
        retained_summary: str,
        task_goal: str,
    ) -> dict[str, float] | None:
        try:
            raw = fn(segment_content, retained_summary, task_goal)
        except Exception as exc:
            logger.debug("generic_backend_call_failed", error=str(exc))
            return None
        return _parse_score_json(raw)

    return _score
