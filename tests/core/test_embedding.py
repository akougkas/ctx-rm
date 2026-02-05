"""Tests for embedding providers (HashingEmbeddingProvider + integration guard)."""

import numpy as np
import pytest

from ctx_rm.core.embedding import (
    HashingEmbeddingProvider,
    cosine_similarity_batch,
)

# ── HashingEmbeddingProvider ────────────────────────────────────────────


def test_hashing_embed_shape_and_dtype():
    provider = HashingEmbeddingProvider()
    vec = provider.embed("hello")
    assert vec.shape == (256,)
    assert vec.dtype == np.float32


def test_hashing_embed_normalized():
    provider = HashingEmbeddingProvider()
    vec = provider.embed("hello world")
    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) < 1e-6


def test_hashing_embed_deterministic():
    provider = HashingEmbeddingProvider()
    a = provider.embed("same text")
    b = provider.embed("same text")
    np.testing.assert_array_equal(a, b)


def test_hashing_embed_empty_string():
    provider = HashingEmbeddingProvider()
    vec = provider.embed("")
    assert vec.shape == (256,)
    # Empty string should not raise; norm may be 0
    norm = float(np.linalg.norm(vec))
    assert norm == pytest.approx(0.0, abs=1e-9)


def test_hashing_embed_batch():
    provider = HashingEmbeddingProvider()
    result = provider.embed_batch(["a", "b", "c"])
    assert result.shape == (3, 256)
    assert result.dtype == np.float32


def test_hashing_similarity_related_texts():
    provider = HashingEmbeddingProvider()
    auth_handler = provider.embed("python auth handler")
    auth_code = provider.embed("python authentication code")
    db_migration = provider.embed("database migration sql")

    sim_related = float(auth_handler @ auth_code)
    sim_unrelated = float(auth_handler @ db_migration)
    assert sim_related > sim_unrelated


def test_cosine_similarity_batch():
    provider = HashingEmbeddingProvider()
    query = provider.embed("authentication")
    stored = provider.embed_batch([
        "auth handler code",
        "database migration",
        "login authentication flow",
    ])
    scores = cosine_similarity_batch(query, stored)
    assert scores.shape == (3,)
    # "login authentication flow" should rank highest
    assert scores[2] > scores[1]


def test_hashing_dimensions_configurable():
    provider = HashingEmbeddingProvider(dimensions=128)
    vec = provider.embed("test")
    assert vec.shape == (128,)
    assert provider.dimensions == 128


# ── SentenceTransformerProvider import guard ─────────────────────────────


def test_sentence_transformer_import_error():
    from ctx_rm.integrations.sentence_transformers import SentenceTransformerProvider

    with pytest.raises(ImportError, match=r"ctx-rm\[embeddings\]"):
        SentenceTransformerProvider()
