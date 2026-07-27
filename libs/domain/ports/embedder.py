from __future__ import annotations

from typing import Protocol


class EmbedderPort(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
