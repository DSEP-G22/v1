"""REQ-ASR-1..12 — transcribes an audio attachment. On terminal failure it still publishes a
`tickets.audio.done` event with status=failed: a silently dropped attachment means the
aggregation window can never close early and will always run to the timeout (see plan §5
pitfalls)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.observability.logging import log_stage
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.repositories import AttachmentRepo, AudioTranscriptRepo
from libs.platform.db.session import session_scope
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
        with tempfile.NamedTemporaryFile(suffix=Path(object_key).suffix or ".wav", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        last_exc: Exception | None = None
        transcript = None
        with log_stage(logger, "audio_svc.transcribe", ticket_id):
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    transcript = ports.transcriber.transcribe(tmp_path, attachment_id)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc

        tmp_path.unlink(missing_ok=True)

        if transcript is None:
            raise last_exc or RuntimeError("transcription failed")

        with session_scope(engine) as session:
            AudioTranscriptRepo(session).upsert(
                attachment_id=attachment_id,
                text=transcript.text,
                segments=[s.model_dump(mode="json") for s in transcript.segments],
                language=transcript.language,
                duration_s=transcript.duration_s,
                acoustic_sentiment=transcript.acoustic_sentiment,
                confidence=transcript.confidence,
                low_confidence=transcript.low_confidence,
                model_version=transcript.model_version,
            )
            AttachmentRepo(session).set_status(attachment_id, "DONE")

        status = "done"
        model_version = transcript.model_version

    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        logger.exception("audio_svc failed ticket_id=%s attachment_id=%s", ticket_id, attachment_id)
        with session_scope(engine) as session:
            AttachmentRepo(session).set_status(attachment_id, "FAILED")

    with session_scope(engine) as session:
        outbox.enqueue(
            session,
            Topics.TICKETS_AUDIO_DONE,
            ticket_id,
            EventEnvelope(
                event_id=f"audio-done-{attachment_id}",
                ticket_id=ticket_id,
                stage="audio_svc",
                body={
                    "attachment_id": attachment_id,
                    "status": status,
                    "model_version": model_version,
                    "error": error,
                },
            ),
        )
