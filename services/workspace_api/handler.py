"""REQ-WKS-1..18 business logic, kept separate from the FastAPI route layer so it's directly
unit-testable. Owns `agent_decision` and (narrowly) the state-transition and lock paths of
`ticket`/`queue_projection`; `draft_response.current_text` edits."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine

from libs.domain.contracts.analysis import RecommendationStatus
from libs.domain.enums import DecisionType
from libs.platform.config import Settings
from libs.platform.db.repositories import (
    ActionRecommendationRepo,
    AgentDecisionRepo,
    AttachmentRepo,
    AudioTranscriptRepo,
    CustomerRepo,
    DiagnosisRepo,
    DraftResponseRepo,
    KnowledgeChunkRepo,
    QueueProjectionRepo,
    TicketRepo,
    TriageResultRepo,
    UnifiedPayloadRepo,
    VisualSummaryRepo,
)
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports
from services.action_svc.handler import execute_recommendation
from services.delivery_gateway.handler import DeliveryRefused
from services.delivery_gateway.handler import send as delivery_send


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def list_queue(engine: Engine, department: str | None = None) -> list[dict]:
    with session_scope(engine) as session:
        rows = QueueProjectionRepo(session).list_queue(department=department)
        return [
            {
                "ticket_id": r.ticket_id,
                "department": r.department,
                "priority_band": r.priority_band,
                "priority_score": r.priority_score,
                "department_confidence": r.department_confidence,
                "fault": r.fault,
                "diagnosis_confidence": r.diagnosis_confidence,
                "state": r.state,
                "channel": r.channel,
                "customer_name": r.customer_name,
                "locked_by": r.locked_by,
                "modalities": list(r.modalities or []),
                "flags": list(r.flags or []),
                "created_at": _iso(r.ticket_created_at),
                "sla_due_at": _iso(r.sla_due_at),
                "updated_at": _iso(r.updated_at),
            }
            for r in rows
        ]


def get_ticket_detail(engine: Engine, ticket_id: str) -> dict:
    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        if ticket is None:
            raise NotFound(f"ticket {ticket_id} not found")

        customer = CustomerRepo(session).get(ticket.customer_id)
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        triage = TriageResultRepo(session).get_latest(ticket_id)
        diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
        draft = DraftResponseRepo(session).get_latest(ticket_id)
        citations = DiagnosisRepo(session).citations_for(diagnosis.id) if diagnosis else []
        recommendations = ActionRecommendationRepo(session).list_for_ticket(ticket_id)
        decisions = AgentDecisionRepo(session).list_for_ticket(ticket_id)

        # UI-3 "Evidence" region: each attachment with the artefact its modality produced, so the
        # workspace can show the audio player beside its transcript and the image beside its
        # visual summary without a second round-trip.
        attachment_repo = AttachmentRepo(session)
        transcript_repo = AudioTranscriptRepo(session)
        visual_repo = VisualSummaryRepo(session)
        attachments = []
        for att in attachment_repo.list_for_ticket(ticket_id):
            transcripts = transcript_repo.list_for_attachment(att.id)
            summaries = visual_repo.list_for_attachment(att.id)
            attachments.append(
                {
                    "id": att.id,
                    "modality": att.modality,
                    "status": att.status,
                    "original_filename": att.original_filename,
                    "content_type": att.content_type,
                    "content_url": f"/workspace/tickets/{ticket_id}/attachments/{att.id}/content",
                    "transcript": {
                        "text": transcripts[0].text,
                        "segments": transcripts[0].segments,
                        "language": transcripts[0].language,
                        "duration_s": transcripts[0].duration_s,
                        "acoustic_sentiment": transcripts[0].acoustic_sentiment,
                        "confidence": transcripts[0].confidence,
                        "low_confidence": transcripts[0].low_confidence,
                        "model_version": transcripts[0].model_version,
                    }
                    if transcripts
                    else None,
                    "visual_summary": {
                        "prompt_template": summaries[0].prompt_template,
                        "summary_text": summaries[0].summary_text,
                        "extracted_fields": summaries[0].extracted_fields,
                        "confidence": summaries[0].confidence,
                        "low_confidence": summaries[0].low_confidence,
                        "model_version": summaries[0].model_version,
                    }
                    if summaries
                    else None,
                }
            )

        return {
            "ticket_id": ticket.id,
            "state": ticket.state,
            "channel": ticket.channel,
            "created_at": _iso(ticket.created_at),
            "updated_at": _iso(ticket.updated_at),
            "department": ticket.department,
            "priority_band": ticket.priority_band,
            "priority_score": ticket.priority_score,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "segment": customer.segment,
            }
            if customer
            else None,
            "attachments": attachments,
            "payload": {
                "original_text": payload.original_text,
                "fused_text": payload.fused_text,
                "provenance": payload.provenance,
                "partial": payload.partial,
                "flags": payload.flags,
                "revision": payload.revision,
                "schema_version": payload.schema_version,
            }
            if payload
            else None,
            "triage": {
                "department": triage.department,
                "department_confidence": triage.department_confidence,
                "alternatives": triage.alternatives,
                "sentiment": triage.sentiment,
                "signals": triage.signals,
                "priority_score": triage.priority_score,
                "band": triage.band,
            }
            if triage
            else None,
            "diagnosis": {
                "id": diagnosis.id,
                "intent": diagnosis.intent,
                "fault": diagnosis.fault,
                "confidence": diagnosis.confidence,
                "alternatives": diagnosis.alternatives,
                "rationale": diagnosis.rationale,
                "needs_human_diagnosis": diagnosis.needs_human_diagnosis,
                "citations": [
                    {
                        "chunk_id": c.chunk_id,
                        "chunk_version": c.chunk_version,
                        "relevance": c.relevance,
                        "verified": c.verified,
                        "excerpt": _chunk_excerpt(session, c.chunk_id),
                    }
                    for c in citations
                ],
            }
            if diagnosis
            else None,
            "draft": {
                "id": draft.id,
                "ai_text": draft.ai_text,
                "current_text": draft.current_text,
                "revision": draft.revision,
                "findings": draft.findings,
                "ai_generated": draft.ai_generated,
            }
            if draft
            else None,
            "recommendations": [
                {
                    "id": r.id,
                    "action_id": r.action_id,
                    "parameters": r.parameters,
                    "requires_supervisor": r.requires_supervisor,
                    "status": r.status,
                }
                for r in recommendations
            ],
            "decisions": [
                {
                    "id": d.id,
                    "type": d.type,
                    "actor_id": d.actor_id,
                    "at": _iso(d.at),
                    "reason_code": d.reason_code,
                }
                for d in decisions
            ],
        }


def _chunk_excerpt(session, chunk_id: str, limit: int = 400) -> str | None:
    """UI-3 requires each citation to expand to its source excerpt. Returns None rather than
    raising when the chunk has been superseded, an unresolvable citation is a display concern,
    not an error."""
    chunk = KnowledgeChunkRepo(session).get(chunk_id)
    if chunk is None:
        return None
    return chunk.text[:limit]


def get_attachment_bytes(ports: Ports, engine: Engine, ticket_id: str, attachment_id: str) -> tuple[bytes, str, str]:
    """Streams stored media back to the workspace (audio player, image thumbnails). Scoped by
    ticket_id so an attachment id alone cannot be used to read another ticket's evidence."""
    with session_scope(engine) as session:
        att = AttachmentRepo(session).get(attachment_id)
        if att is None or att.ticket_id != ticket_id:
            raise NotFound(f"attachment {attachment_id} not found on ticket {ticket_id}")
        object_key, content_type, filename = att.object_key, att.content_type, att.original_filename

    return ports.object_store.get(object_key), content_type, filename


def lock_ticket(engine: Engine, ticket_id: str, username: str) -> None:
    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        if ticket is None:
            raise NotFound(f"ticket {ticket_id} not found")
        projection = QueueProjectionRepo(session)
        row = projection.get(ticket_id)
        if row is not None and row.locked_by and row.locked_by != username:
            raise Conflict(f"ticket {ticket_id} is already locked by {row.locked_by}")

        if ticket.state == "READY_FOR_AGENT":
            TicketRepo(session).update_state(ticket_id, "READY_FOR_AGENT", "IN_REVIEW")
        projection.set_lock(ticket_id, username)

    from services.projector_svc.handler import sync_state

    sync_state(engine, ticket_id)


def update_draft(engine: Engine, ticket_id: str, new_text: str) -> dict:
    with session_scope(engine) as session:
        draft = DraftResponseRepo(session).get_latest(ticket_id)
        if draft is None:
            raise NotFound(f"no draft_response for ticket {ticket_id}")
        DraftResponseRepo(session).update_current_text(draft.id, new_text)
        return {"draft_id": draft.id, "revision": draft.revision + 1}


def approve_and_send(ports: Ports, engine: Engine, settings: Settings, *, ticket_id: str, actor_id: str) -> dict:
    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        draft = DraftResponseRepo(session).get_latest(ticket_id)
        if ticket is None or draft is None:
            raise NotFound(f"ticket or draft not found for {ticket_id}")

        customer = CustomerRepo(session).get(ticket.customer_id)
        to_address = (customer.email if customer and customer.email else None) or (
            f"{(customer.name if customer else 'customer').lower().replace(' ', '.')}@example.invalid"
        )

        decision = AgentDecisionRepo(session).create(
            ticket_id=ticket_id,
            type=DecisionType.APPROVE_SEND.value,
            actor_id=actor_id,
            reason_code=None,
            before=draft.ai_text,
            after=draft.current_text,
        )
        TicketRepo(session).update_state(ticket_id, "IN_REVIEW", "RESOLVED")

        approval_id = decision.id
        draft_id = draft.id
        current_text = draft.current_text
        channel = ticket.channel

    try:
        result = delivery_send(
            ports.mail_gateway,
            engine,
            ticket_id=ticket_id,
            draft_response_id=draft_id,
            approval_id=approval_id,
            channel=channel,
            to_address=to_address,
            subject=f"Re: your support ticket {ticket_id}",
            body=current_text,
        )
    except DeliveryRefused as exc:
        raise Conflict(str(exc)) from exc

    from services.projector_svc.handler import sync_state

    sync_state(engine, ticket_id)
    return {"approval_id": approval_id, **result}


def reject_draft(engine: Engine, ticket_id: str, actor_id: str, reason_code: str | None) -> dict:
    with session_scope(engine) as session:
        draft = DraftResponseRepo(session).get_latest(ticket_id)
        decision = AgentDecisionRepo(session).create(
            ticket_id=ticket_id,
            type=DecisionType.REJECT.value,
            actor_id=actor_id,
            reason_code=reason_code,
            before=draft.ai_text if draft else None,
            after=None,
        )
        TicketRepo(session).update_state(ticket_id, "IN_REVIEW", "READY_FOR_AGENT")
        QueueProjectionRepo(session).set_lock(ticket_id, None)

    from services.projector_svc.handler import sync_state

    sync_state(engine, ticket_id)
    return {"decision_id": decision.id}


def execute_action(ports: Ports, engine: Engine, *, ticket_id: str, recommendation_id: str) -> dict:
    return execute_recommendation(
        ports.action_adapter, engine, ticket_id=ticket_id, recommendation_id=recommendation_id
    )


def reassign_ticket(engine: Engine, ticket_id: str, actor_id: str, department: str, reason_code: str | None) -> dict:
    """UI-3 `Reassign`. Routes the ticket to another department and records the decision, which is
    what feeds the routing-accuracy metric on the supervisor dashboard."""
    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        if ticket is None:
            raise NotFound(f"ticket {ticket_id} not found")
        before = ticket.department
        ticket.department = department
        decision = AgentDecisionRepo(session).create(
            ticket_id=ticket_id,
            type=DecisionType.REASSIGN.value,
            actor_id=actor_id,
            reason_code=reason_code,
            before=before,
            after=department,
        )
        decision_id = decision.id

    from services.projector_svc.handler import sync_state

    sync_state(engine, ticket_id)
    return {"decision_id": decision_id, "department": department}


def escalate_ticket(engine: Engine, ticket_id: str, actor_id: str, reason_code: str | None) -> dict:
    """UI-3 `Escalate`. Raises the band to critical and unlocks, so the ticket re-enters the queue
    pinned at the top for a supervisor to pick up."""
    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        if ticket is None:
            raise NotFound(f"ticket {ticket_id} not found")
        before = ticket.priority_band
        ticket.priority_band = "critical"
        ticket.priority_score = max(ticket.priority_score or 0, 80)
        decision = AgentDecisionRepo(session).create(
            ticket_id=ticket_id,
            type=DecisionType.ESCALATE.value,
            actor_id=actor_id,
            reason_code=reason_code,
            before=before,
            after="critical",
        )
        QueueProjectionRepo(session).set_lock(ticket_id, None)
        decision_id = decision.id

    from services.projector_svc.handler import sync_state

    sync_state(engine, ticket_id)
    return {"decision_id": decision_id, "priority_band": "critical"}


def dashboard_metrics(engine: Engine) -> dict:
    """UI-4 supervisor dashboard. Queue depth and ageing come from the projection; acceptance,
    edit and rejection rates come from the decision log, which is the only record of what the
    human actually did with each AI draft."""
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        rows = QueueProjectionRepo(session).list_queue()
        decisions = AgentDecisionRepo(session).list_all()

        open_states = {"READY_FOR_AGENT", "IN_REVIEW", "AWAITING_APPROVAL"}
        by_department: dict[str, dict[str, Any]] = {}
        by_band: dict[str, int] = {}
        ageing = {"lt_1h": 0, "h1_4": 0, "h4_24": 0, "gt_24h": 0}
        sla_at_risk: list[dict] = []
        workload: dict[str, int] = {}

        for r in rows:
            dept = r.department or "unassigned"
            entry = by_department.setdefault(dept, {"department": dept, "open": 0, "total": 0})
            entry["total"] += 1
            if r.state in open_states:
                entry["open"] += 1
                by_band[r.priority_band or "unknown"] = by_band.get(r.priority_band or "unknown", 0) + 1

                created = r.ticket_created_at
                if created is not None:
                    age_h = (now - _aware(created)).total_seconds() / 3600
                    if age_h < 1:
                        ageing["lt_1h"] += 1
                    elif age_h < 4:
                        ageing["h1_4"] += 1
                    elif age_h < 24:
                        ageing["h4_24"] += 1
                    else:
                        ageing["gt_24h"] += 1

                if r.sla_due_at is not None:
                    minutes_left = (_aware(r.sla_due_at) - now).total_seconds() / 60
                    if minutes_left < 120:
                        sla_at_risk.append(
                            {
                                "ticket_id": r.ticket_id,
                                "department": dept,
                                "priority_band": r.priority_band,
                                "minutes_left": round(minutes_left, 1),
                                "breached": minutes_left < 0,
                            }
                        )
            if r.locked_by:
                workload[r.locked_by] = workload.get(r.locked_by, 0) + 1

        approvals = [d for d in decisions if d.type == DecisionType.APPROVE_SEND.value]
        edited = [d for d in approvals if (d.before or "") != (d.after or "")]
        rejections = [d for d in decisions if d.type == DecisionType.REJECT.value]
        reviewed = len(approvals) + len(rejections)

        return {
            "generated_at": now.isoformat(),
            "queue_depth_by_department": sorted(by_department.values(), key=lambda e: -e["open"]),
            "queue_depth_by_band": by_band,
            "ageing": ageing,
            "sla_at_risk": sorted(sla_at_risk, key=lambda e: e["minutes_left"]),
            "agent_workload": [{"agent": k, "locked": v} for k, v in sorted(workload.items(), key=lambda kv: -kv[1])],
            "ai_outcomes": {
                "reviewed": reviewed,
                "approved": len(approvals),
                "approved_unedited": len(approvals) - len(edited),
                "approved_edited": len(edited),
                "rejected": len(rejections),
                "acceptance_rate": (len(approvals) / reviewed) if reviewed else None,
                "edit_rate": (len(edited) / len(approvals)) if approvals else None,
                "rejection_rate": (len(rejections) / reviewed) if reviewed else None,
            },
        }


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes even for timezone-aware columns; treat them as UTC so
    the ageing and SLA arithmetic does not raise."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
