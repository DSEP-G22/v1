"""Maintains `queue_projection` from `tickets.ready` and from workspace commands (lock/state
changes wired in workspace_api). The queue read path never joins the analysis tables, it reads
this projection only."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope
from libs.platform.config import Settings
from libs.platform.db.repositories import (
    AttachmentRepo,
    CustomerRepo,
    DiagnosisRepo,
    QueueProjectionRepo,
    TicketRepo,
    TriageResultRepo,
    UnifiedPayloadRepo,
)
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports

# SRS §5.1 resolution targets per band, used only to render the UI-2 SLA countdown.
SLA_HOURS_BY_BAND = {"critical": 4, "high": 8, "normal": 24, "low": 72}


def _project(session, ticket_id: str) -> dict | None:
    ticket = TicketRepo(session).get(ticket_id)
    if ticket is None:
        return None

    customer = CustomerRepo(session).get(ticket.customer_id)
    triage = TriageResultRepo(session).get_latest(ticket_id)
    diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
    payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
    attachments = AttachmentRepo(session).list_for_ticket(ticket_id)

    modalities = sorted({a.modality for a in attachments})
    if payload is not None and payload.original_text.strip():
        modalities = ["text", *modalities]

    band = ticket.priority_band or (triage.band if triage else None)
    sla_due_at = None
    if band in SLA_HOURS_BY_BAND:
        sla_due_at = ticket.created_at + timedelta(hours=SLA_HOURS_BY_BAND[band])

    return {
        "department": ticket.department,
        "priority_band": band,
        "state": ticket.state,
        "customer_name": customer.name if customer else "unknown",
        "channel": ticket.channel,
        "priority_score": ticket.priority_score if ticket.priority_score is not None else (triage.priority_score if triage else None),
        "department_confidence": triage.department_confidence if triage else None,
        "fault": diagnosis.fault if diagnosis else None,
        "diagnosis_confidence": diagnosis.confidence if diagnosis else None,
        "modalities": modalities,
        "flags": list(payload.flags) if payload else [],
        "ticket_created_at": ticket.created_at,
        "sla_due_at": sla_due_at,
    }


def handle_ready(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    ticket_id = envelope.ticket_id
    with session_scope(engine) as session:
        fields = _project(session, ticket_id)
        if fields is None:
            return
        QueueProjectionRepo(session).upsert(ticket_id, **fields)


def sync_state(engine: Engine, ticket_id: str) -> None:
    """Refreshes the projection after a workspace command (lock, approve, reject, reassign)
    changes the ticket without going through tickets.ready again."""
    with session_scope(engine) as session:
        projection = QueueProjectionRepo(session)
        if projection.get(ticket_id) is None:
            return
        fields = _project(session, ticket_id)
        if fields is not None:
            projection.upsert(ticket_id, **fields)
