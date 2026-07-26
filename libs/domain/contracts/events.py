"""Broker envelope and topic names — SAD §6.4 / Figure 9."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0.0"
    event_id: str
    ticket_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stage: str
    body: dict[str, Any] = Field(default_factory=dict)


class Topics:
    TICKETS_RAW = "tickets.raw"
    TICKETS_AUDIO_WORK = "tickets.audio.work"
    TICKETS_IMAGE_WORK = "tickets.image.work"
    TICKETS_TEXT_WORK = "tickets.text.work"
    TICKETS_AUDIO_DONE = "tickets.audio.done"
    TICKETS_IMAGE_DONE = "tickets.image.done"
    TICKETS_TEXT_DONE = "tickets.text.done"
    TICKETS_AGGREGATED = "tickets.aggregated"
    TICKETS_TRIAGED = "tickets.triaged"
    TICKETS_DIAGNOSED = "tickets.diagnosed"
    TICKETS_READY = "tickets.ready"
    TICKETS_DLQ = "tickets.dlq"

    ALL = (
        TICKETS_RAW,
        TICKETS_AUDIO_WORK,
        TICKETS_IMAGE_WORK,
        TICKETS_TEXT_WORK,
        TICKETS_AUDIO_DONE,
        TICKETS_IMAGE_DONE,
        TICKETS_TEXT_DONE,
        TICKETS_AGGREGATED,
        TICKETS_TRIAGED,
        TICKETS_DIAGNOSED,
        TICKETS_READY,
        TICKETS_DLQ,
    )
