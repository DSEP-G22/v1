"""Builds `fused_text` and exact-offset `Provenance` spans. The only place fused text is built —
callers must not reconstruct or re-derive it by any other path (SAD §5.2.1)."""

from __future__ import annotations

from libs.domain.contracts.media import AudioTranscript, VisualSummary
from libs.domain.contracts.payload import Provenance
from libs.domain.enums import Modality

_SEPARATOR = "\n\n"


def fuse(
    original_text: str,
    transcripts: list[AudioTranscript],
    visual_summaries: list[VisualSummary],
) -> tuple[str, list[Provenance]]:
    fragments: list[str] = []
    provenance_specs: list[tuple[Modality, str, float, str | None]] = []

    stripped_original = original_text.strip()
    if stripped_original:
        fragments.append(f"[CUSTOMER_TEXT] {stripped_original}")
        provenance_specs.append((Modality.text, "original_text", 1.0, None))

    for transcript in transcripts:
        fragments.append(f"[AUDIO:{transcript.attachment_id}] {transcript.text}")
        provenance_specs.append(
            (Modality.audio, transcript.attachment_id, transcript.confidence, transcript.model_version)
        )

    for summary in visual_summaries:
        fragments.append(f"[IMAGE:{summary.attachment_id}] {summary.summary_text}")
        provenance_specs.append(
            (Modality.image, summary.attachment_id, summary.confidence, summary.model_version)
        )

    fused_text = _SEPARATOR.join(fragments)

    provenance: list[Provenance] = []
    offset = 0
    for fragment, (modality, source, confidence, model_version) in zip(fragments, provenance_specs):
        span = (offset, offset + len(fragment))
        provenance.append(
            Provenance(
                modality=modality,
                source=source,
                span=span,
                confidence=confidence,
                model_version=model_version,
            )
        )
        offset += len(fragment) + len(_SEPARATOR)

    return fused_text, provenance
