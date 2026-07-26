"""Per-modality extraction contracts (audio transcripts, visual summaries)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Segment(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_s: float
    end_s: float
    text: str
    confidence: float


class AudioTranscript(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: str
    text: str
    segments: list[Segment] = Field(default_factory=list)
    language: str
    duration_s: float
    acoustic_sentiment: str
    confidence: float
    low_confidence: bool
    model_version: str


class LedState(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    colour: str
    behaviour: str


class ExtractedFields(BaseModel):
    model_config = ConfigDict(frozen=True)

    device_model: str | None = None
    led_states: list[LedState] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    numeric_values: dict[str, float] = Field(default_factory=dict)


class VisualSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: str
    prompt_template: str
    summary_text: str
    extracted_fields: ExtractedFields
    confidence: float
    low_confidence: bool
    model_version: str
