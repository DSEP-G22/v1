"""REQ-FUS-1..10 — the statechart of SAD §6.5. Records each per-modality result idempotently
against `aggregation_state`; emits when the completion set is satisfied, or emits a partial
payload when the window expires. The timer is a single sweeper thread scanning for expired rows
every 5s (see `sweep`) — never a per-ticket `threading.Timer`."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.domain.contracts.media import AudioTranscript, ExtractedFields, LedState, Segment, VisualSummary
from libs.domain.contracts.payload import PayloadInvalid, validate_payload
from libs.domain.enums import FlagCode
from libs.domain.policy.fusion import fuse
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.repositories import (
    AggregationReceivedItemRepo,
    AggregationStateRepo,
    AttachmentRepo,
    AudioTranscriptRepo,
    TicketRepo,
    UnifiedPayloadRepo,
    VisualSummaryRepo,
)
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports

logger = logging.getLogger(__name__)


def _row_to_transcript(row) -> AudioTranscript:
    return AudioTranscript(
        attachment_id=row.attachment_id,
        text=row.text,
        segments=[Segment.model_validate(s) for s in row.segments],
        language=row.language,
        duration_s=row.duration_s,
        acoustic_sentiment=row.acoustic_sentiment,
        confidence=row.confidence,
        low_confidence=row.low_confidence,
        model_version=row.model_version,
    )


def _row_to_visual_summary(row) -> VisualSummary:
    fields = row.extracted_fields or {}
    return VisualSummary(
        attachment_id=row.attachment_id,
        prompt_template=row.prompt_template,
        summary_text=row.summary_text,
        extracted_fields=ExtractedFields(
            device_model=fields.get("device_model"),
            led_states=[LedState.model_validate(led) for led in fields.get("led_states", [])],
            error_codes=fields.get("error_codes", []),
            numeric_values=fields.get("numeric_values", {}),
        ),
        confidence=row.confidence,
        low_confidence=row.low_confidence,
        model_version=row.model_version,
    )


def _finalize(session: Session, ticket_id: str) -> bool:
    """Returns True if a payload was written."""
    agg_repo = AggregationStateRepo(session)
    state = agg_repo.get_by_ticket(ticket_id)
    if state is None or state.status != "OPEN":
        return False

    attachments = AttachmentRepo(session).list_for_ticket(ticket_id)
    audio_atts = [a for a in attachments if a.modality == "audio"]
    image_atts = [a for a in attachments if a.modality == "image"]

    audio_repo = AudioTranscriptRepo(session)
    visual_repo = VisualSummaryRepo(session)

    transcripts: list[AudioTranscript] = []
    missing = False
    for att in audio_atts:
        rows = audio_repo.list_for_attachment(att.id)
        if rows:
            transcripts.append(_row_to_transcript(rows[-1]))
        else:
            missing = True

    visual_summaries: list[VisualSummary] = []
    for att in image_atts:
        rows = visual_repo.list_for_attachment(att.id)
        if rows:
            visual_summaries.append(_row_to_visual_summary(rows[-1]))
        else:
            missing = True

    received = AggregationReceivedItemRepo(session).list_for(ticket_id)
    if set(received) < set(state.expected_set):
        missing = True  # window expired before every item was received at all

    low_conf_flags: list[str] = []
    if any(t.low_confidence for t in transcripts):
        low_conf_flags.append(FlagCode.LOW_ASR_CONFIDENCE.value)
    if any(v.low_confidence for v in visual_summaries):
        low_conf_flags.append(FlagCode.LOW_VLM_CONFIDENCE.value)

    fused_text, provenance = fuse(state.original_text, transcripts, visual_summaries)

    flags = list(state.text_flags) + low_conf_flags
    if missing:
        flags.append(FlagCode.PARTIAL_PAYLOAD.value)

    payload_repo = UnifiedPayloadRepo(session)
    latest = payload_repo.get_latest(ticket_id)
    revision = (latest.revision + 1) if latest else 1

    row_kwargs = dict(
        ticket_id=ticket_id,
        revision=revision,
        schema_version="1.0.0",
        original_text=state.original_text,
        fused_text=fused_text,
        provenance=[p.model_dump(mode="json") for p in provenance],
        flags=sorted(set(flags)),
        partial=missing,
        payload_metadata={},
    )

    try:
        from libs.domain.contracts.payload import UnifiedTicketPayload

        candidate = UnifiedTicketPayload(customer_id="", channel="", **row_kwargs)
        validate_payload(candidate)
    except PayloadInvalid as exc:
        logger.warning("aggregator: payload validation failed ticket_id=%s error=%s", ticket_id, exc)

    payload_repo.create(**row_kwargs)
    TicketRepo(session).update_state(ticket_id, "PROCESSING", "AGGREGATED")
    agg_repo.set_status(ticket_id, "CLOSED")

    outbox.enqueue(
        session,
        Topics.TICKETS_AGGREGATED,
        ticket_id,
        EventEnvelope(
            event_id=f"aggregated-{ticket_id}-{revision}",
            ticket_id=ticket_id,
            stage="aggregator_svc",
            body={"revision": revision, "partial": missing},
        ),
    )
    return True


def _handle_done(item: str, ports: Ports, engine: Engine, envelope: EventEnvelope, *, text: str | None = None, text_flags: list[str] | None = None) -> None:
    ticket_id = envelope.ticket_id
    should_finalize = False

    with session_scope(engine) as session:
        agg_repo = AggregationStateRepo(session)
        state = agg_repo.get_by_ticket(ticket_id)
        if state is None:
            logger.warning("aggregator: no aggregation_state for ticket_id=%s (item=%s)", ticket_id, item)
            return
        if text is not None:
            agg_repo.set_text(ticket_id, text, text_flags or [])

        received_repo = AggregationReceivedItemRepo(session)
        received_repo.mark(ticket_id, item)
        received = received_repo.list_for(ticket_id)

        should_finalize = set(received) >= set(state.expected_set)

    if should_finalize:
        # Finalize in a brand-new transaction, never the one that just marked completion: this
        # transaction's own commit only guarantees it saw everything committed *before* it
        # started, but sibling done-handlers (e.g. text_svc's set_text) may commit concurrently
        # under SQLite's snapshot isolation and would otherwise be invisible to a reused session.
        with session_scope(engine) as session:
            _finalize(session, ticket_id)


def handle_text_done(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    _handle_done(
        "text",
        ports,
        engine,
        envelope,
        text=envelope.body.get("normalized_text", ""),
        text_flags=envelope.body.get("flags", []),
    )


def handle_audio_done(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    _handle_done(f"audio:{envelope.body['attachment_id']}", ports, engine, envelope)


def handle_image_done(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    _handle_done(f"image:{envelope.body['attachment_id']}", ports, engine, envelope)


def sweep(ports: Ports, engine: Engine, settings: Settings) -> int:
    """Scans for expired aggregation windows and finalises them as partial payloads. Called by
    a single background sweeper thread every 5s — never one threading.Timer per ticket."""
    finalized = 0
    with session_scope(engine) as session:
        now = datetime.now(timezone.utc)
        expired = AggregationStateRepo(session).list_expired(now)
        ticket_ids = [row.ticket_id for row in expired]

    for ticket_id in ticket_ids:
        with session_scope(engine) as session:
            if _finalize(session, ticket_id):
                finalized += 1
    return finalized
