"""Configuration for ctx-rm — Pydantic settings with env/file support."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class CtxRmConfig(BaseSettings):
    """Global configuration, loaded from env vars or .env file."""

    model_config = {"env_prefix": "CTX_RM_"}

    # Token budget for active context
    token_budget: int = Field(default=200_000, description="Max tokens in active context")

    # Headroom: keep this fraction of budget free
    headroom_ratio: float = Field(default=0.15, description="Fraction of budget to keep free")

    # Eviction policy
    policy: str = Field(default="budget", description="Eviction policy: lru, clock, budget")
    eviction_batch_mode: Literal["fixed", "adaptive"] = Field(
        default="fixed",
        description="Eviction batch mode: fixed or adaptive",
    )
    adaptive_single_evict_max_utilization: float = Field(
        default=1.0,
        description=(
            "In adaptive mode, switch to one-at-a-time eviction when utilization "
            "is at or below this value"
        ),
    )

    # Scorer settings
    recency_halflife: float = Field(default=300.0, description="Recency decay halflife in seconds")

    # Warm cache settings
    warm_max_items: int = Field(default=64, description="Max segments in warm cache")
    warm_max_tokens: int = Field(default=50_000, description="Max tokens in warm cache")

    # Watcher settings
    watcher_interval: float = Field(default=5.0, description="Watcher check interval in seconds")
    watcher_threshold: float = Field(default=0.70, description="Utilization threshold for eviction")

    # Storage
    db_path: Path = Field(default=Path(":memory:"), description="SQLite DB path for cold store")

    # LlamaCpp driver settings
    llama_base_url: str = Field(
        default="http://192.168.86.141:8080",
        description="llama-server base URL",
    )
    llama_temperature: float = Field(default=0.3, description="LlamaCpp temperature")
    llama_max_tokens: int = Field(default=4096, description="LlamaCpp max completion tokens")
    llama_timeout: float = Field(default=120.0, description="LlamaCpp request timeout in seconds")
    llama_max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for transient llama-server failures",
    )
    llama_retry_base_delay: float = Field(
        default=0.5,
        description="Base retry backoff in seconds for llama-server calls",
    )
    llama_retry_max_delay: float = Field(
        default=8.0,
        description="Maximum retry backoff in seconds for llama-server calls",
    )
    llama_retry_jitter: float = Field(
        default=0.25,
        description="Maximum random jitter added to llama-server retry backoff",
    )
    llama_auto_discover_context_window: bool = Field(
        default=True,
        description="Auto-discover model context window from /v1/models metadata",
    )
    llama_context_window: int | None = Field(
        default=None,
        description="Optional explicit context window override (tokens)",
    )

    # LLM Scoring (opt-in)
    scorer: str = Field(default="heuristic", description="Scorer: heuristic, ollama, or sequential")
    ollama_host: str = Field(
        default="http://localhost:11434", description="Ollama API host"
    )
    ollama_model: str | None = Field(
        default=None, description="Preferred Ollama model (None=auto)"
    )
    ollama_max_concurrent: int = Field(
        default=4, description="Max concurrent Ollama scoring requests"
    )

    # Sequential scorer LLM backend (opt-in)
    sequential_backend: str = Field(
        default="lexical",
        description="Sequential backend: lexical or ollama",
    )
    sequential_backend_host: str = Field(
        default="http://localhost:11434",
        description="LLM backend host for sequential scorer",
    )
    sequential_backend_model: str = Field(
        default="llama3.2:3b",
        description="LLM model for sequential scorer backend",
    )

    # Output
    output_dir: Path = Field(default=Path("./results"), description="Results output directory")
    log_level: str = Field(default="INFO", description="Logging level")
