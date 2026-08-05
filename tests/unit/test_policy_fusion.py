from libs.domain.contracts.media import AudioTranscript, ExtractedFields, VisualSummary
from libs.domain.policy.fusion import fuse


def _transcript(attachment_id: str, text: str) -> AudioTranscript:
    return AudioTranscript(
        attachment_id=attachment_id,
        text=text,
        segments=[],
        language="en",
        duration_s=5.0,
        acoustic_sentiment="neutral",
        confidence=0.9,
        low_confidence=False,
        model_version="test-asr-1.0",
    )


def _visual(attachment_id: str, text: str) -> VisualSummary:
    return VisualSummary(
        attachment_id=attachment_id,
        prompt_template="generic",
        summary_text=text,
        extracted_fields=ExtractedFields(),
        confidence=0.8,
        low_confidence=False,
        model_version="test-vlm-1.0",
    )


def test_fuse_spans_exact_for_every_fragment():
    fused_text, provenance = fuse(
        original_text="My router has a red light.",
        transcripts=[_transcript("att-audio-1", "It stopped working yesterday.")],
        visual_summaries=[_visual("att-image-1", "Red power LED visible.")],
    )

    assert len(provenance) == 3
    for prov in provenance:
        start, end = prov.span
        fragment = fused_text[start:end]
        assert fragment.startswith(f"[{'CUSTOMER_TEXT' if prov.source == 'original_text' else prov.modality.value.upper() + ':' + prov.source}]")


def test_fuse_empty_original_text_is_skipped():
    fused_text, provenance = fuse(
        original_text="   ",
        transcripts=[_transcript("att-audio-1", "Hello")],
        visual_summaries=[],
    )
    assert "[CUSTOMER_TEXT]" not in fused_text
    assert len(provenance) == 1
    assert provenance[0].source == "att-audio-1"


def test_fuse_no_fragments_yields_empty_text():
    fused_text, provenance = fuse("", [], [])
    assert fused_text == ""
    assert provenance == []
