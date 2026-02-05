"""Pydantic v2 models for the benchmark task YAML schema.

Defines the complete type hierarchy for loading
``docs/context_removal_benchmark_tasks.yaml`` into validated Python objects.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator

# ── Needle & Context Injection ──────────────────────────────────────────────


class Needle(BaseModel):
    """A fact or code snippet injected at a specific turn."""

    id: str
    type: Literal["fact", "code"]
    injection_turn: int
    injection_method: str
    content: str
    risk_if_evicted: str


class ContextInjection(BaseModel):
    """A block of noise tokens injected at a specific turn."""

    turn: int
    type: str
    size_tokens: int
    description: str


# ── Evaluation Check Types ──────────────────────────────────────────────────


class FileContainsCheck(BaseModel):
    """Assert that a file contains a specific substring."""

    check: Literal["file_contains"]
    target: str
    must_include: str


class FileNotContainsCheck(BaseModel):
    """Assert that a file does NOT contain a specific substring.

    Note: ``must_include`` names the string that must be *absent*.
    The field name matches the YAML schema.
    """

    check: Literal["file_not_contains"]
    target: str
    must_include: str


class FileContainsInOrderCheck(BaseModel):
    """Assert that a file contains substrings in the given order."""

    check: Literal["file_contains_in_order"]
    target: str
    must_include_order: list[str]


class FileEqualsCheck(BaseModel):
    """Assert that a file still contains a preserved substring.

    Semantics: substring containment (not exact file equality).
    The ``must_preserve`` string must still appear in the file.
    """

    check: Literal["file_equals"]
    target: str
    must_preserve: str


EvalCheck = Annotated[
    FileContainsCheck | FileNotContainsCheck | FileContainsInOrderCheck | FileEqualsCheck,
    Discriminator("check"),
]


# ── Task & Suite ────────────────────────────────────────────────────────────


class Task(BaseModel):
    """A single benchmark task definition."""

    id: str
    title: str
    expected_winner: str
    eviction_pressure: str
    min_turns: int
    repo_fixture: str
    scenario: str
    needles: list[Needle]
    context_injections: list[ContextInjection]
    success_criteria: list[str]
    evaluation: list[EvalCheck]


class BenchmarkSuite(BaseModel):
    """Top-level container: the full benchmark YAML parsed into typed models."""

    schema_version: int
    benchmark_name: str
    description: str
    tasks: list[Task]
