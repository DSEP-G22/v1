"""REQ-ING-8, REQ-FUS-4, consumes tickets.raw, opens the aggregation window with the expected
completion set, and fans out to the three .work topics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.repositories import AggregationStateRepo, AttachmentRepo
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports


def handle(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    ticket_id = envelope.ticket_id
    original_text = envelope.body.get("original_text", "")

    with session_scope(engine) as session:
        attachments = AttachmentRepo(session).list_for_ticket(ticket_id)
        audio_atts = [a for a in attachments if a.modality == "audio"]
        image_atts = [a for a in attachments if a.modality == "image"]

        expected_set = ["text"] + [f"audio:{a.id}" for a in audio_atts] + [f"image:{a.id}" for a in image_atts]

        AggregationStateRepo(session).create(
            ticket_id=ticket_id,
            expected_set=expected_set,
            window_expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.aggregation_window_s),
            status="OPEN",
        )

        outbox.enqueue(
            session,
            Topics.TICKETS_TEXT_WORK,
            ticket_id,
            EventEnvelope(
                event_id=f"text-work-{ticket_id}",
                ticket_id=ticket_id,
                stage="routing",
                body={"original_text": original_text},
            ),
        )

        for att in audio_atts:
            outbox.enqueue(
                session,
                Topics.TICKETS_AUDIO_WORK,
                ticket_id,
                EventEnvelope(
                    event_id=f"audio-work-{att.id}",
                    ticket_id=ticket_id,
                    stage="routing",
                    body={"attachment_id": att.id, "object_key": att.object_key},
                ),
            )

        for att in image_atts:
            outbox.enqueue(
                session,
                Topics.TICKETS_IMAGE_WORK,
                ticket_id,
                EventEnvelope(
                    event_id=f"image-work-{att.id}",
                    ticket_id=ticket_id,
                    stage="routing",
                    body={"attachment_id": att.id, "object_key": att.object_key},
                ),
            )
