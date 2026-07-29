"""EmbedderPort implementations."""

from __future__ import annotations

import hashlib

import numpy as np

_HASH_DIM = 384


class HashEmbedder:
    """Deterministic hashing vectorizer, no model download — used in CI (`embedder_impl=hash_stub`)."""

    model_version = "hash-embedder-384"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = np.zeros(_HASH_DIM, dtype="float32")
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % _HASH_DIM
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.model_version = model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return embeddings.tolist()
