"""SentenceTransformer embedding provider (optional dependency).

Requires: pip install ctx-rm[embeddings]
"""

from __future__ import annotations

import numpy as np

from ctx_rm.core.embedding import EmbeddingProvider


class SentenceTransformerProvider(EmbeddingProvider):
    """Embedding provider backed by sentence-transformers models.

    Lazy-imports sentence-transformers at init time; raises ImportError
    with install instructions if the package is not available.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for SentenceTransformerProvider. "
                "Install with: pip install ctx-rm[embeddings]"
            ) from None

        self._model = SentenceTransformer(model_name)
        self._dimensions: int = self._model.get_sentence_embedding_dimension()

    @property
    def name(self) -> str:
        return "sentence-transformers"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, text: str) -> np.ndarray:
        vec = self._model.encode(text, normalize_embeddings=True)
        return np.asarray(vec, dtype=np.float32)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)
