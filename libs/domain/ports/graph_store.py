from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class Subgraph(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    procedures: list[dict[str, Any]]
    actions: list[dict[str, Any]]


class GraphStorePort(Protocol):
    def expand(self, seed_terms: list[str], hops: int = 2) -> Subgraph: ...
