"""REQ-FLT-1..14 — retrieval, LLM diagnosis, citation verification. Consumes tickets.triaged,
writes diagnosis + citation, publishes tickets.diagnosed."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.repositories import DiagnosisRepo, TicketRepo, UnifiedPayloadRepo
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports
from services.retrieval_svc.handler import safe_assemble_context

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "models" / "prompts" / "llm" / "diagnosis.txt"


class _CitationOut(BaseModel):
    chunk_id: str
    relevance: float = 0.5


class _DiagnosisOut(BaseModel):
    intent: str = "unknown"
    fault: str | None = None
    confidence: float = 0.0
    alternatives: list[str] = Field(default_factory=list)
    rationale: str = ""
    citations: list[_CitationOut] = Field(default_factory=list)


def _verify_citations(citations: list[_CitationOut], known_chunk_ids: set[str]) -> tuple[list[dict], bool]:
    """Drops citations whose chunk_id was not actually in the retrieved context. Returns the
    kept citations (as dicts ready for DiagnosisRepo.create) and whether any were dropped."""
    kept: list[dict] = []
    any_dropped = False
    for c in citations:
        if c.chunk_id in known_chunk_ids:
            kept.append({"chunk_id": c.chunk_id, "chunk_version": 1, "relevance": c.relevance, "verified": True})
        else:
            any_dropped = True
    return kept, any_dropped


def handle(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    ticket_id = envelope.ticket_id

    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        if ticket is None or payload is None:
            return
        fused_text = payload.fused_text
        department = ticket.department

    context = safe_assemble_context(ports, fused_text, department=department)

    prompt_template = (
        _PROMPT_PATH.read_text(encoding="utf-8")
        if _PROMPT_PATH.exists()
        else "Diagnose this ticket:\n{fused_text}\nContext:\n{context}"
    )
    prompt = prompt_template.format(fused_text=fused_text, context=context.context_text or "(no context retrieved)")

    try:
        generator = ports.text_generator
        if hasattr(generator, "generate_json"):
            result: _DiagnosisOut = generator.generate_json(prompt, _DiagnosisOut, prompt_kind="diagnosis")
        else:
            raw = generator.generate(prompt, prompt_kind="diagnosis")
            import json

            result = _DiagnosisOut.model_validate(json.loads(raw))
    except Exception:
        logger.exception("orchestrator_svc: diagnosis generation failed ticket_id=%s", ticket_id)
        result = _DiagnosisOut(rationale="LLM unavailable; diagnosis could not be generated.")

    kept_citations, any_dropped = _verify_citations(result.citations, context.chunk_ids())
    needs_human = result.confidence < settings.diagnosis_min_confidence or any_dropped

    with session_scope(engine) as session:
        DiagnosisRepo(session).create(
            ticket_id=ticket_id,
            intent=result.intent,
            fault=result.fault,
            confidence=result.confidence,
            alternatives=result.alternatives,
            rationale=result.rationale,
            needs_human_diagnosis=needs_human,
            citations=kept_citations,
        )
        TicketRepo(session).update_state(ticket_id, "TRIAGED", "DIAGNOSED")
        outbox.enqueue(
            session,
            Topics.TICKETS_DIAGNOSED,
            ticket_id,
            EventEnvelope(event_id=f"diagnosed-{ticket_id}", ticket_id=ticket_id, stage="orchestrator_svc", body={}),
        )
