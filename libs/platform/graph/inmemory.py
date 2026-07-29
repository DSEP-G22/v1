"""In-memory graph loaded from config/seed/graph_seed.yaml — SAD deviation table substitute for
Neo4j (~200 nodes in the demo)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from libs.domain.ports.graph_store import Subgraph


class InMemoryGraphStore:
    def __init__(self, seed_path: Path) -> None:
        data = yaml.safe_load(Path(seed_path).read_text(encoding="utf-8"))
        self._nodes: dict[str, dict[str, Any]] = {n["id"]: n for n in data.get("nodes", [])}
        self._edges: list[dict[str, Any]] = data.get("edges", [])
        self._out_edges: dict[str, list[dict[str, Any]]] = {}
        for edge in self._edges:
            self._out_edges.setdefault(edge["from"], []).append(edge)

    def _match_seed_terms(self, seed_terms: list[str]) -> set[str]:
        lowered_terms = [t.lower() for t in seed_terms]
        matched: set[str] = set()
        for node_id, node in self._nodes.items():
            haystacks = [node_id.lower()] + [str(v).lower() for v in node.get("props", {}).values()]
            if any(term in haystack for term in lowered_terms for haystack in haystacks):
                matched.add(node_id)
        return matched

    def expand(self, seed_terms: list[str], hops: int = 2) -> Subgraph:
        frontier = self._match_seed_terms(seed_terms)
        visited_nodes: set[str] = set(frontier)
        visited_edges: list[dict[str, Any]] = []

        for _ in range(hops):
            next_frontier: set[str] = set()
            for node_id in frontier:
                for edge in self._out_edges.get(node_id, []):
                    visited_edges.append(edge)
                    if edge["to"] not in visited_nodes:
                        next_frontier.add(edge["to"])
                        visited_nodes.add(edge["to"])
            frontier = next_frontier
            if not frontier:
                break

        nodes = [self._nodes[n] | {"id": n} for n in visited_nodes if n in self._nodes]
        procedures = [n for n in nodes if n.get("label") == "Procedure"]
        actions = [n for n in nodes if n.get("label") == "Action"]

        return Subgraph(nodes=nodes, edges=visited_edges, procedures=procedures, actions=actions)
