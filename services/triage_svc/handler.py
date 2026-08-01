"""REQ-CLS-*, REQ-PRI-* — classifies department, scores priority, writes triage_result."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.domain.enums import Department, Sentiment
from libs.domain.policy import priority as priority_policy
from libs.domain.policy import routing as routing_policy
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.repositories import CustomerRepo, TicketRepo, TriageResultRepo, UnifiedPayloadRepo
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTING_RULES_PATH = _REPO_ROOT / "config" / "routing_rules.yaml"

_URGENCY_KEYWORDS = ("urgent", "immediately", "asap", "emergency", "critical")
_ANGRY_MARKERS = ("angry", "furious", "unacceptable", "ridiculous", "worst", "outrageous")
_FRUSTRATED_MARKERS = ("frustrated", "again", "still not", "third time", "annoyed", "fed up")
_OUTAGE_MARKERS = ("outage", "no internet", "no signal", "entire area", "whole street", "everyone")


def _load_routing_rules() -> list[dict]:
    if not _ROUTING_RULES_PATH.exists():
        return []
    data = yaml.safe_load(_ROUTING_RULES_PATH.read_text(encoding="utf-8")) or {}
    return data.get("rules", [])


_ROUTING_RULES = _load_routing_rules()


def _infer_sentiment(text: str) -> tuple[Sentiment, float]:
    lowered = text.lower()
    if any(m in lowered for m in _ANGRY_MARKERS):
        return Sentiment.angry, 1.0
    if any(m in lowered for m in _FRUSTRATED_MARKERS):
        return Sentiment.frustrated, 0.6
    return Sentiment.neutral, 0.0


def _build_triage_inputs(text: str, customer_segment: str, prior_ticket_count: int) -> priority_policy.TriageInputs:
    _, sentiment_score = _infer_sentiment(text)
    lowered = text.lower()
    return {
        "sentiment_score": sentiment_score,
        "urgency_keyword_hit": any(k in lowered for k in _URGENCY_KEYWORDS),
        "customer_segment_score": {"premium": 1.0, "standard": 0.3}.get(customer_segment, 0.3),
        "outage_scope_score": 0.7 if any(m in lowered for m in _OUTAGE_MARKERS) else 0.0,
        "prior_contacts_score": min(prior_ticket_count / 5.0, 1.0),
        "sla_age_score": 0.0,
    }


def handle(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    ticket_id = envelope.ticket_id

    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        if ticket is None or payload is None:
            return

        customer = CustomerRepo(session).get(ticket.customer_id)
        customer_segment = customer.segment if customer else "standard"

        from sqlalchemy import func, select

        from libs.platform.db.models import Ticket as TicketRow

        prior_count = session.execute(
            select(func.count()).select_from(TicketRow).where(TicketRow.customer_id == ticket.customer_id)
        ).scalar_one()

        fused_text = payload.fused_text
        try:
            department, department_confidence, alt_pairs = ports.classifier.classify(fused_text)
        except Exception:
            logger.exception("triage_svc: classifier failed ticket_id=%s, defaulting to general", ticket_id)
            department, department_confidence, alt_pairs = Department.general, 0.0, []

        final_department = routing_policy.evaluate(
            _ROUTING_RULES, {"text": fused_text, "classifier_department": department}
        )

        sentiment, _ = _infer_sentiment(fused_text)
        triage_inputs = _build_triage_inputs(fused_text, customer_segment, prior_count)
        score, band, signals = priority_policy.score(triage_inputs)

        TriageResultRepo(session).create(
            ticket_id=ticket_id,
            department=final_department.value,
            department_confidence=department_confidence,
            alternatives=[d.value for d, _ in alt_pairs],
            sentiment=sentiment.value,
            signals=[s.model_dump(mode="json") for s in signals],
            priority_score=score,
            band=band.value,
        )

        TicketRepo(session).update_triage_summary(ticket_id, final_department.value, score, band.value)
        TicketRepo(session).update_state(ticket_id, "AGGREGATED", "TRIAGED")

        outbox.enqueue(
            session,
            Topics.TICKETS_TRIAGED,
            ticket_id,
            EventEnvelope(event_id=f"triaged-{ticket_id}", ticket_id=ticket_id, stage="triage_svc", body={}),
        )
