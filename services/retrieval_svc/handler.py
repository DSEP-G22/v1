"""Retrieval library, not a broker consumer. Dense top-k over the vector index, graph expansion
from extracted entities, then a bounded context assembler (max ~2500 chars, dedupe by chunk id).
Used by orchestrator_svc."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from libs.domain.ports.graph_store import Subgraph
from libs.platform.registry import Ports

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 2500
TOP_K = 8

_ENTITY_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]{3,}")


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    relevance: float
    source: str


@dataclass
class RetrievalContext:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    subgraph: Subgraph | None = None
    context_text: str = ""

    def chunk_ids(self) -> set[str]:
        return {c.chunk_id for c in self.chunks}


def _extract_seed_terms(text: str, max_terms: int = 12) -> list[str]:
    words = _ENTITY_WORD_RE.findall(text.lower())
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
        if len(seen) >= max_terms:
            break
    return seen


def assemble_context(ports: Ports, query_text: str, department: str | None = None, k: int = TOP_K) -> RetrievalContext:
    embedding = ports.embedder.embed([query_text])[0]
    filters = {"department": department} if department else None
    raw_hits = ports.vector_index.query(embedding, k=k, filters=filters)

    seed_terms = _extract_seed_terms(query_text)
    subgraph = ports.graph_store.expand(seed_terms, hops=2)

    seen_ids: set[str] = set()
    chunks: list[RetrievedChunk] = []
    for text, relevance, metadata in raw_hits:
        chunk_id = metadata.get("chunk_id", "")
        if chunk_id in seen_ids:
            continue
        seen_ids.add(chunk_id)
        chunks.append(RetrievedChunk(chunk_id=chunk_id, text=text, relevance=relevance, source=metadata.get("doc_id", "")))

    context_parts: list[str] = []
    total_chars = 0
    for chunk in chunks:
        fragment = f"[{chunk.chunk_id}] {chunk.text}"
        if total_chars + len(fragment) > MAX_CONTEXT_CHARS:
            break
        context_parts.append(fragment)
        total_chars += len(fragment)

    for proc in subgraph.procedures:
        fragment = f"[proc:{proc['id']}] {proc.get('props', {}).get('name', '')}"
        if total_chars + len(fragment) > MAX_CONTEXT_CHARS:
            break
        context_parts.append(fragment)
        total_chars += len(fragment)

    return RetrievalContext(chunks=chunks, subgraph=subgraph, context_text="\n".join(context_parts))


def safe_assemble_context(ports: Ports, query_text: str, department: str | None = None, k: int = TOP_K) -> RetrievalContext:
    """Same as assemble_context, but never raises, a degraded embedder/vector index/graph
    store must not block diagnosis/response generation; it should just retrieve nothing
    (REQ-FLT degradation: G7)."""
    try:
        return assemble_context(ports, query_text, department=department, k=k)
    except Exception:
        logger.exception("retrieval_svc: assemble_context failed, continuing with empty context")
        return RetrievalContext()
