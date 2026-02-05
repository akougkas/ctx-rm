"""Embedding providers for semantic search in cold storage.

Pluggable embedding interface: start with zero-ML hashing (feature hashing
via numpy + hashlib), optionally upgrade to sentence-transformers or other
model-backed providers.

All providers produce L2-normalized float32 vectors for consistent
cosine similarity via dot product.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import numpy as np


class EmbeddingProvider(ABC):
    """Base protocol for embedding providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Output embedding dimensionality."""

    @abstractmethod
    def embed(self, text: str) -> np.ndarray:
        """Embed a single text string.

        Returns:
            1-D float32 ndarray of shape (dimensions,), L2-normalized.
        """

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed multiple texts.

        Default implementation iterates embed(). Subclasses with native
        batching should override for efficiency.

        Returns:
            2-D float32 ndarray of shape (len(texts), dimensions).
        """
        return np.stack([self.embed(t) for t in texts])


class HashingEmbeddingProvider(EmbeddingProvider):
    """Zero-ML embedding via feature hashing (character n-grams).

    Uses hashlib.md5 to hash character n-grams into a fixed-dimensional
    vector with sign flipping, then L2-normalizes. Deterministic and
    fast, no model files needed.
    """

    def __init__(
        self,
        dimensions: int = 256,
        ngram_range: tuple[int, int] = (2, 4),
    ) -> None:
        self._dimensions = dimensions
        self._ngram_range = ngram_range

    @property
    def name(self) -> str:
        return "hashing"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dimensions, dtype=np.float32)
        text_lower = text.lower()

        for n in range(self._ngram_range[0], self._ngram_range[1] + 1):
            for i in range(len(text_lower) - n + 1):
                gram = text_lower[i : i + n]
                h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
                idx = h % self._dimensions
                sign = 1.0 if (h >> 63) & 1 else -1.0
                vec[idx] += sign

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm

        return vec


def cosine_similarity_batch(query: np.ndarray, stored: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between a query and stored embeddings.

    For pre-normalized vectors, cosine similarity equals the dot product.

    Args:
        query: 1-D vector of shape (d,).
        stored: 2-D matrix of shape (n, d).

    Returns:
        1-D array of shape (n,) with similarity scores.
    """
    return stored @ query
