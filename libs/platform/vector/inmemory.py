"""NumPy in-memory vector index, JSON-persisted. Small corpus (<10k chunks) — SAD deviation
table substitute for Qdrant. Refuses to query when the persisted `embedding_model` differs from
the one this instance was configured with (SAD §9.4) — stale vectors silently degrade retrieval
quality far worse than a loud failure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


class EmbeddingModelMismatch(RuntimeError):
    pass


class InMemoryVectorIndex:
    def __init__(self, path: Path, embedding_model: str) -> None:
        self._path = Path(path)
        self._embedding_model = embedding_model
        self._ids: list[str] = []
        self._doc_ids: list[str] = []
        self._texts: list[str] = []
        self._metadata: list[dict[str, Any]] = []
        self._matrix: np.ndarray = np.zeros((0, 0), dtype="float32")
        self._mismatched = False
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text(encoding="utf-8"))
        stored_model = data.get("embedding_model")
        if stored_model is not None and stored_model != self._embedding_model:
            self._mismatched = True
            return
        records = data.get("records", [])
        self._ids = [r["chunk_id"] for r in records]
        self._doc_ids = [r["doc_id"] for r in records]
        self._texts = [r["text"] for r in records]
        self._metadata = [r["metadata"] for r in records]
        if records:
            self._matrix = np.array([r["embedding"] for r in records], dtype="float32")

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "chunk_id": self._ids[i],
                "doc_id": self._doc_ids[i],
                "text": self._texts[i],
                "embedding": self._matrix[i].tolist(),
                "metadata": self._metadata[i],
            }
            for i in range(len(self._ids))
        ]
        self._path.write_text(
            json.dumps({"embedding_model": self._embedding_model, "records": records}), encoding="utf-8"
        )

    def upsert(
        self, doc_id: str, chunks: list[str], embeddings: list[list[float]], metadata: list[dict[str, Any]]
    ) -> None:
        if self._mismatched:
            raise EmbeddingModelMismatch(
                f"vector index at {self._path} was built with a different embedding_model; rebuild it"
            )
        self.delete_by_doc(doc_id)
        new_matrix = np.array(embeddings, dtype="float32")
        for i, chunk_text in enumerate(chunks):
            self._ids.append(f"{doc_id}:{i}")
            self._doc_ids.append(doc_id)
            self._texts.append(chunk_text)
            self._metadata.append(metadata[i] if i < len(metadata) else {})
        self._matrix = new_matrix if self._matrix.size == 0 else np.vstack([self._matrix, new_matrix])
        self._save()

    def query(
        self, embedding: list[float], k: int = 8, filters: dict[str, Any] | None = None
    ) -> list[tuple[str, float, dict[str, Any]]]:
        if self._mismatched:
            raise EmbeddingModelMismatch(
                f"vector index at {self._path} was built with a different embedding_model; rebuild it"
            )
        if not self._ids:
            return []

        query_vec = np.array(embedding, dtype="float32")
        query_norm = np.linalg.norm(query_vec) or 1.0
        matrix_norms = np.linalg.norm(self._matrix, axis=1)
        matrix_norms[matrix_norms == 0] = 1.0
        similarities = (self._matrix @ query_vec) / (matrix_norms * query_norm)

        candidates = list(range(len(self._ids)))
        if filters:
            candidates = [
                i
                for i in candidates
                if all(self._metadata[i].get(key) == value for key, value in filters.items())
            ]

        ranked = sorted(candidates, key=lambda i: similarities[i], reverse=True)[:k]
        return [
            (self._texts[i], float(similarities[i]), {"chunk_id": self._ids[i], **self._metadata[i]})
            for i in ranked
        ]

    def delete_by_doc(self, doc_id: str) -> None:
        keep = [i for i, d in enumerate(self._doc_ids) if d != doc_id]
        self._ids = [self._ids[i] for i in keep]
        self._doc_ids = [self._doc_ids[i] for i in keep]
        self._texts = [self._texts[i] for i in keep]
        self._metadata = [self._metadata[i] for i in keep]
        self._matrix = self._matrix[keep] if self._matrix.size else self._matrix
