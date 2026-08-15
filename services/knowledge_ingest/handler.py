"""REQ-ONB-1..10, parses Markdown/PDF/TXT into heading-aware chunks, embeds them, upserts the
vector index, and writes knowledge_document/knowledge_chunk plus a data-quality report.

Not a broker consumer: called directly by scripts/seed.py and admin_api's onboarding endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import Engine

from libs.platform.db.repositories import KnowledgeChunkRepo, KnowledgeDocumentRepo
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports
from services.knowledge_ingest.chunk import CHUNK_SIZE, heading_aware_chunks

_ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}(?:\s[A-Z][a-zA-Z]{2,})?\b")


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(f"pypdf is required to ingest {path.name}; install it or use .md/.txt") from exc
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

    return path.read_text(encoding="utf-8")


def _extract_entities(text: str, max_entities: int = 20) -> list[str]:
    """Cheap capitalised-phrase heuristic, good enough to flag candidate device models / fault
    names for a human reviewer; not fed back into the (static, seeded) demo graph in v1."""
    seen: list[str] = []
    for m in _ENTITY_RE.finditer(text):
        candidate = m.group(0)
        if candidate not in seen:
            seen.append(candidate)
        if len(seen) >= max_entities:
            break
    return seen


@dataclass
class IngestReport:
    document_id: str
    title: str
    num_chunks: int
    avg_chunk_len: float
    chunks_too_short: int
    chunks_too_long: int
    entities: list[str] = field(default_factory=list)


def ingest_path(ports: Ports, engine: Engine, *, org_id: str, path: Path, doc_type: str | None = None) -> IngestReport:
    text = _read_text(path)
    chunks = heading_aware_chunks(text)
    entities = _extract_entities(text)

    embeddings = ports.embedder.embed(chunks) if chunks else []

    with session_scope(engine) as session:
        doc = KnowledgeDocumentRepo(session).create(
            org_id=org_id,
            title=path.stem.replace("_", " ").replace("-", " ").title(),
            source_path=str(path),
            doc_type=doc_type or path.suffix.lstrip(".") or "unknown",
        )
        document_id = doc.id

        chunk_repo = KnowledgeChunkRepo(session)
        embedding_model = getattr(ports.embedder, "model_version", "unknown")
        for i, chunk_text in enumerate(chunks):
            chunk_repo.create(
                document_id=document_id, chunk_index=i, text=chunk_text, embedding_model=embedding_model
            )

    if chunks:
        ports.vector_index.upsert(
            doc_id=document_id,
            chunks=chunks,
            embeddings=embeddings,
            metadata=[{"doc_id": document_id, "chunk_index": i} for i in range(len(chunks))],
        )

    lengths = [len(c) for c in chunks] or [0]
    return IngestReport(
        document_id=document_id,
        title=path.stem,
        num_chunks=len(chunks),
        avg_chunk_len=sum(lengths) / len(lengths),
        chunks_too_short=sum(1 for l in lengths if l < 100),
        chunks_too_long=sum(1 for l in lengths if l > CHUNK_SIZE * 1.2),
        entities=entities,
    )


def ingest_directory(ports: Ports, engine: Engine, *, org_id: str, directory: Path) -> list[IngestReport]:
    reports: list[IngestReport] = []
    for path in sorted(directory.glob("*")):
        if path.suffix.lower() not in (".md", ".txt", ".pdf"):
            continue
        reports.append(ingest_path(ports, engine, org_id=org_id, path=path))
    return reports
