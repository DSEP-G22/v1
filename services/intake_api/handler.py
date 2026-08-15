"""Ticket intake, REQ-ING-1..15. Validates media by sniffing magic bytes (never the declared
MIME type), stores it, and writes ticket + attachment + outbox(tickets.raw) in one transaction."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.domain.enums import Modality
from libs.platform.db import outbox
from libs.platform.db.repositories import AttachmentRepo, CustomerRepo, TicketRepo
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports
from services.intake_api.magic import UnsupportedMediaType, sniff_media

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


@dataclass
class InboundFile:
    filename: str
    data: bytes


class TicketCreationError(ValueError):
    pass


class DuplicateIdempotencyKey(ValueError):
    def __init__(self, ticket_id: str) -> None:
        super().__init__(f"idempotency key already used, existing ticket_id={ticket_id}")
        self.ticket_id = ticket_id


def create_ticket(
    ports: Ports,
    engine: Engine,
    *,
    customer_id: str,
    channel: str,
    text: str,
    files: list[InboundFile],
    idempotency_key: str | None,
) -> str:
    with session_scope(engine) as session:
        customer = CustomerRepo(session).get(customer_id)
        if customer is None:
            raise TicketCreationError(f"unknown customer_id {customer_id}")

        ticket_repo = TicketRepo(session)

        if idempotency_key:
            from sqlalchemy import select

            from libs.platform.db.models import Ticket as TicketRow

            existing = session.execute(
                select(TicketRow).where(
                    TicketRow.org_id == customer.org_id, TicketRow.idempotency_key == idempotency_key
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise DuplicateIdempotencyKey(existing.id)

        validated_files: list[tuple[InboundFile, str, Modality]] = []
        for f in files:
            if len(f.data) > MAX_ATTACHMENT_BYTES:
                raise TicketCreationError(f"{f.filename} exceeds max attachment size")
            try:
                content_type, modality = sniff_media(f.data)
            except UnsupportedMediaType as exc:
                raise TicketCreationError(f"{f.filename}: {exc}") from exc
            validated_files.append((f, content_type, modality))

        ticket = ticket_repo.create(
            org_id=customer.org_id,
            customer_id=customer.id,
            channel=channel,
            state="RECEIVED",
            idempotency_key=idempotency_key,
        )
        ticket_repo.update_state(ticket.id, "RECEIVED", "PROCESSING")

        attachment_repo = AttachmentRepo(session)
        for inbound_file, content_type, modality in validated_files:
            object_key = ports.object_store.put(customer.org_id, inbound_file.filename, inbound_file.data)
            attachment_repo.create(
                ticket_id=ticket.id,
                modality=modality.value,
                object_key=object_key,
                status="PENDING",
                original_filename=inbound_file.filename,
                content_type=content_type,
            )

        outbox.enqueue(
            session,
            Topics.TICKETS_RAW,
            ticket.id,
            EventEnvelope(
                event_id=f"raw-{ticket.id}",
                ticket_id=ticket.id,
                stage="intake",
                body={"original_text": text or ""},
            ),
        )

        return ticket.id


def get_status(engine: Engine, ticket_id: str) -> dict | None:
    with session_scope(engine) as session:
        ticket = TicketRepo(session).get(ticket_id)
        if ticket is None:
            return None
        return {
            "ticket_id": ticket.id,
            "state": ticket.state,
            "department": ticket.department,
            "priority_score": ticket.priority_score,
            "priority_band": ticket.priority_band,
        }
