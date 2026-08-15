"""REQ-RES-1..12, drafts a customer reply, runs compliance checks, selects an action
recommendation, and transitions the ticket to READY_FOR_AGENT."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.domain.policy import action_selection as action_selection_policy
from libs.domain.policy import compliance as compliance_policy
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.repositories import (
    ActionRecommendationRepo,
    ActionRegistryEntryRepo,
    DiagnosisRepo,
    DraftResponseRepo,
    TicketRepo,
    UnifiedPayloadRepo,
)
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports
from services.retrieval_svc.handler import safe_assemble_context

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "models" / "prompts" / "llm" / "draft.txt"


class _DraftOut(BaseModel):
    ai_text: str = ""


def _to_registry_entries(rows) -> list[action_selection_policy.ActionRegistryEntry]:
    return [
        action_selection_policy.ActionRegistryEntry(
            action_id=row.action_id,
            mapped_faults=row.mapped_faults,
            requires_supervisor=row.requires_supervisor,
            enabled=row.enabled,
            requires_fields=row.requires_fields,
            impact_limits=row.impact_limits,
        )
        for row in rows
    ]


def handle(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    ticket_id = envelope.ticket_id

    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
        if ticket is None or payload is None or diagnosis is None:
            return
        fused_text = payload.fused_text
        department = ticket.department
        fault = diagnosis.fault
        diagnosis_confidence = diagnosis.confidence
        rationale = diagnosis.rationale
        registry_rows = ActionRegistryEntryRepo(session).list_all()

    context = safe_assemble_context(ports, fused_text, department=department)

    prompt_template = (
        _PROMPT_PATH.read_text(encoding="utf-8")
        if _PROMPT_PATH.exists()
        else "Draft a reply for:\n{fused_text}\nContext:\n{context}"
    )
    prompt = prompt_template.format(
        fault=fault or "unknown",
        confidence=diagnosis_confidence,
        rationale=rationale,
        context=context.context_text or "(no context retrieved)",
        fused_text=fused_text,
    )

    try:
        generator = ports.text_generator
        if hasattr(generator, "generate_json"):
            draft_out: _DraftOut = generator.generate_json(prompt, _DraftOut, prompt_kind="draft")
        else:
            raw = generator.generate(prompt, prompt_kind="draft")
            draft_out = _DraftOut.model_validate(json.loads(raw))
    except Exception:
        logger.exception("response_svc: draft generation failed ticket_id=%s", ticket_id)
        draft_out = _DraftOut(ai_text="")

    ai_text = draft_out.ai_text or "Hi, thanks for reaching out, we're looking into this now."
    findings = compliance_policy.check(ai_text)

    registry_entries = _to_registry_entries(registry_rows)
    action_params = {"ticket_id": ticket_id}
    recommendation = None
    if fault:
        recommendation = action_selection_policy.select(fault, registry_entries, action_params)

    with session_scope(engine) as session:
        DraftResponseRepo(session).create(
            ticket_id=ticket_id,
            ai_text=ai_text,
            current_text=ai_text,
            revision=1,
            findings=[f.model_dump(mode="json") for f in findings],
            ai_generated=True,
        )

        if recommendation is not None:
            ActionRecommendationRepo(session).create(
                ticket_id=ticket_id,
                action_id=recommendation.action_id,
                parameters=recommendation.parameters,
                requires_supervisor=recommendation.requires_supervisor,
                status=recommendation.status,
            )

        TicketRepo(session).update_state(ticket_id, "DIAGNOSED", "READY_FOR_AGENT")

        outbox.enqueue(
            session,
            Topics.TICKETS_READY,
            ticket_id,
            EventEnvelope(event_id=f"ready-{ticket_id}", ticket_id=ticket_id, stage="response_svc", body={}),
        )
