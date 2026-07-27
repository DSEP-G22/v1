from __future__ import annotations

from typing import Any, Protocol


class VectorIndexPort(Protocol):
    def upsert(
        self, doc_id: str, chunks: list[str], embeddings: list[list[float]], metadata: list[dict[str, Any]]
    ) -> None: ...

    def query(
        self, embedding: list[float], k: int = 8, filters: dict[str, Any] | None = None
    ) -> list[tuple[str, float, dict[str, Any]]]: ...

    def delete_by_doc(self, doc_id: str) -> None: ...
