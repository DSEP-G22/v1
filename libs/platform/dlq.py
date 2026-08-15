"""Durably captures `tickets.dlq` events (the in-process broker's DLQ topic has no persistence
of its own) so admin_api can list and replay them. Wired once by runtime/wiring.py, not owned
by any single `services/*` package, so it lives in the platform layer."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.domain.ports.event_broker import EventBrokerPort
from libs.platform.db.repositories import DlqEntryRepo
from libs.platform.db.session import session_scope


def _capture(engine: Engine, envelope: EventEnvelope) -> None:
    body = envelope.body
    with session_scope(engine) as session:
        DlqEntryRepo(session).create(
            ticket_id=envelope.ticket_id,
            original_topic=body.get("original_topic", ""),
            original_group=body.get("original_group", ""),
            error=body.get("error", ""),
            attempts=body.get("attempts", 0),
            body=body,
        )


def install_dlq_capture(broker: EventBrokerPort, engine: Engine) -> None:
    broker.subscribe(Topics.TICKETS_DLQ, "dlq_capture", lambda env: _capture(engine, env))
