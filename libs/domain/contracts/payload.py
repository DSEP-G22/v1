"""UnifiedTicketPayload — the fused, multimodal artefact per SRS Appendix B.5."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from libs.domain.contracts.media import AudioTranscript, VisualSummary
from libs.domain.enums import Modality


class PayloadInvalid(ValueError):
    pass


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    modality: Modality
    source: str
    span: tuple[int, int]
    confidence: float
    model_version: str | None = None


class UnifiedTicketPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0.0"
    ticket_id: str
    customer_id: str
    channel: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    original_text: str
    transcripts: list[AudioTranscript] = Field(default_factory=list)
    visual_summaries: list[VisualSummary] = Field(default_factory=list)
    fused_text: str
    provenance: list[Provenance] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    partial: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    revision: int = 1


def validate_payload(payload: UnifiedTicketPayload) -> None:
    if not payload.fused_text.strip():
        raise PayloadInvalid(f"ticket {payload.ticket_id}: fused_text is empty")

    fused_len = len(payload.fused_text)
    spans_sorted = sorted((p.span for p in payload.provenance), key=lambda s: s[0])
    prev_end = None
    for start, end in spans_sorted:
        if start < 0 or end > fused_len or start > end:
            raise PayloadInvalid(
                f"ticket {payload.ticket_id}: span ({start}, {end}) exceeds fused_text length {fused_len}"
            )
        if prev_end is not None and start < prev_end:
            raise PayloadInvalid(
                f"ticket {payload.ticket_id}: provenance spans overlap at offset {start}"
            )
        prev_end = end
