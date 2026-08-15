"""REQ-VLM-1..12, extracts structured fields from an image attachment. Mirrors audio_svc's
failure handling: a terminal failure still publishes tickets.image.done with status=failed."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.observability.logging import log_stage
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.repositories import AttachmentRepo, VisualSummaryRepo
from libs.platform.db.session import session_scope
from libs.platform.models.vlm import choose_template
from libs.platform.registry import Ports

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2


def handle(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    ticket_id = envelope.ticket_id
    attachment_id = envelope.body["attachment_id"]
    object_key = envelope.body["object_key"]

    status = "failed"
    model_version: str | None = None
    error: str | None = None

    try:
        data = ports.object_store.get(object_key)
        template = choose_template(Path(object_key).name)
        with tempfile.NamedTemporaryFile(suffix=Path(object_key).suffix or ".png", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        last_exc: Exception | None = None
        summary = None
        with log_stage(logger, "image_svc.extract", ticket_id):
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    summary = ports.visual_extractor.extract(tmp_path, attachment_id, template)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc

        tmp_path.unlink(missing_ok=True)

        if summary is None:
            raise last_exc or RuntimeError("visual extraction failed")

        with session_scope(engine) as session:
            VisualSummaryRepo(session).upsert(
                attachment_id=attachment_id,
                prompt_template=summary.prompt_template,
                summary_text=summary.summary_text,
                extracted_fields=summary.extracted_fields.model_dump(mode="json"),
                confidence=summary.confidence,
                low_confidence=summary.low_confidence,
                model_version=summary.model_version,
            )
            AttachmentRepo(session).set_status(attachment_id, "DONE")

        status = "done"
        model_version = summary.model_version

    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        logger.exception("image_svc failed ticket_id=%s attachment_id=%s", ticket_id, attachment_id)
        with session_scope(engine) as session:
            AttachmentRepo(session).set_status(attachment_id, "FAILED")

    with session_scope(engine) as session:
        outbox.enqueue(
            session,
            Topics.TICKETS_IMAGE_DONE,
            ticket_id,
            EventEnvelope(
                event_id=f"image-done-{attachment_id}",
                ticket_id=ticket_id,
                stage="image_svc",
                body={
                    "attachment_id": attachment_id,
                    "status": status,
                    "model_version": model_version,
                    "error": error,
                },
            ),
        )
