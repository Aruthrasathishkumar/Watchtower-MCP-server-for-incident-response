"""Embedding utilities for semantic similarity scoring.

Uses sentence-transformers with a lightweight 384-dim model. Suitable
for CPU-only inference. Model is lazily loaded on first use.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np


log = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model():
    """Load the sentence-transformer model exactly once per process."""
    from sentence_transformers import SentenceTransformer
    log.info("Loading embedding model %s (first use, ~80MB download if absent)", _MODEL_NAME)
    return SentenceTransformer(_MODEL_NAME)


def embed_text(text: str) -> list[float]:
    """Generate an embedding for a single text string."""
    if not text:
        return [0.0] * _EMBEDDING_DIM
    model = _get_model()
    # Normalise so cosine similarity is equivalent to dot product
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Batch-embed many texts. Much faster than calling embed_text in a loop."""
    if not texts:
        return []
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return [v.tolist() for v in vecs]