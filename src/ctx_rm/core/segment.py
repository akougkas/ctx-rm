"""Segment: the atomic unit of context in ctx-rm.

A Segment represents a single piece of content in the context window — a user
message, assistant response, tool output, file read, or any other content block.
Segments flow through tiers: Active → Warm → Cold → Graveyard, and can be
recalled as Zombies (page-fault semantics from OS virtual memory).
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SegmentRole(StrEnum):
    """Role of the content producer."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    CONTEXT = "context"


class Tier(StrEnum):
    """Memory tier — maps to OS/DB buffer pool concepts.

    Active   = buffer pool hot pages (in the LLM context window)
    Warm     = recently evicted, fast recall (in-memory cache)
    Cold     = persistent store, needs search (SQLite + embeddings)
    Graveyard = append-only archive (compressed, immutable)
    Zombie   = page-fault recall staging (validation before re-entry)
    """

    ACTIVE = "active"
    WARM = "warm"
    COLD = "cold"
    GRAVEYARD = "graveyard"
    ZOMBIE = "zombie"


class Segment(BaseModel):
    """A single chunk of context with tier metadata.

    Inspired by OS page table entries: each segment tracks its tier, access
    pattern (recency + frequency), pinning state, and scoring metadata.
    """

    seg_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str
    role: SegmentRole
    token_count: int = 0
    pinned: bool = False

    # Lifecycle timestamps
    created_at: float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)
    evicted_at: float | None = None
    recalled_at: float | None = None

    # Access pattern tracking (for LRU/LFU/ARC policies)
    access_count: int = 0
    ref_bit: bool = True  # CLOCK algorithm reference bit

    # Current tier
    tier: Tier = Tier.ACTIVE

    # Scoring (filled by Scorer)
    relevance_score: float | None = None
    staleness_score: float | None = None
    redundancy_score: float | None = None
    composite_score: float | None = None

    # Eviction audit trail
    eviction_reason: str | None = None
    eviction_policy: str | None = None

    # Optional references
    embedding_ref: str | None = None
    summary: str | None = None

    # Source metadata (where this segment came from)
    source: str | None = None  # e.g., "file_read:src/auth.py", "tool:bash", "user_message"
    turn_number: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        """Record an access — updates recency, frequency, and ref bit."""
        self.last_accessed = time.time()
        self.access_count += 1
        self.ref_bit = True

    def evict(self, reason: str, policy: str) -> None:
        """Mark this segment as evicted."""
        self.evicted_at = time.time()
        self.eviction_reason = reason
        self.eviction_policy = policy
        # Tier transition is handled by the TieredStore

    def recall(self) -> None:
        """Mark this segment as recalled (zombie → active)."""
        self.recalled_at = time.time()
        self.tier = Tier.ZOMBIE
        self.touch()

    @property
    def age_seconds(self) -> float:
        """Seconds since creation."""
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        """Seconds since last access."""
        return time.time() - self.last_accessed

    def __repr__(self) -> str:
        role = self.role.value[:4]
        tier = self.tier.value[:3]
        tokens = self.token_count
        return f"<Seg {self.seg_id} {role}/{tier} {tokens}tok>"
