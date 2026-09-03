"""TranscriberPort implementations."""

from __future__ import annotations

import math
from pathlib import Path

from libs.domain.contracts.media import AudioTranscript, Segment


_NO_TRANSCRIPT_TEXT = (
    "Transcript unavailable in stub mode; provide a .txt sidecar next to the audio "
    "for deterministic testing without inventing a customer report."
)


class StubTranscriber:
    """Returns a transcript only when a `.txt` sidecar exists. Without one, it avoids inventing
    a customer claim and returns a neutral placeholder instead."""

    def __init__(self, model_version: str = "stub-asr-1.0", low_confidence_threshold: float = 0.60) -> None:
        self._model_version = model_version
        self._threshold = low_confidence_threshold

    def transcribe(self, audio_path: Path, attachment_id: str) -> AudioTranscript:
        sidecar = Path(audio_path).with_suffix(".txt")
        if sidecar.exists():
            text = sidecar.read_text(encoding="utf-8").strip()
        else:
            text = _NO_TRANSCRIPT_TEXT
        if not text:
            text = _NO_TRANSCRIPT_TEXT
        confidence = 0.92
        return AudioTranscript(
            attachment_id=attachment_id,
            text=text,
            segments=[Segment(start_s=0.0, end_s=5.0, text=text, confidence=confidence)],
            language="en",
            duration_s=5.0,
            acoustic_sentiment="neutral",
            confidence=confidence,
            low_confidence=confidence < self._threshold,
            model_version=self._model_version,
        )


class FasterWhisperTranscriber:
    """Wraps faster-whisper. Segment-level `avg_logprob` is converted to a confidence via
    `exp()`, then duration-weighted-averaged across segments."""

    def __init__(self, model_size: str = "base", low_confidence_threshold: float = 0.60) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self._model_version = f"faster-whisper-{model_size}"
        self._threshold = low_confidence_threshold

    def transcribe(self, audio_path: Path, attachment_id: str) -> AudioTranscript:
        segments_iter, info = self._model.transcribe(
            str(audio_path), language=None, task="translate", vad_filter=True
        )
        segments: list[Segment] = []
        weighted_conf_sum = 0.0
        total_duration = 0.0
        text_parts: list[str] = []

        for seg in segments_iter:
            confidence = math.exp(seg.avg_logprob)
            duration = max(seg.end - seg.start, 1e-6)
            segments.append(Segment(start_s=seg.start, end_s=seg.end, text=seg.text.strip(), confidence=confidence))
            weighted_conf_sum += confidence * duration
            total_duration += duration
            text_parts.append(seg.text.strip())

        mean_confidence = weighted_conf_sum / total_duration if total_duration > 0 else 0.0
        acoustic_sentiment = _naive_acoustic_sentiment(segments)

        return AudioTranscript(
            attachment_id=attachment_id,
            text=" ".join(text_parts).strip(),
            segments=segments,
            language=info.language or "en",
            duration_s=total_duration,
            acoustic_sentiment=acoustic_sentiment,
            confidence=mean_confidence,
            low_confidence=mean_confidence < self._threshold,
            model_version=self._model_version,
        )


def _naive_acoustic_sentiment(segments: list[Segment]) -> str:
    """Keyword-proxy sentiment: no prosody model in v1, just a lexical heuristic over the
    transcribed text as a stand-in for tone."""
    joined = " ".join(s.text for s in segments).lower()
    angry_markers = ("angry", "furious", "unacceptable", "ridiculous", "worst")
    frustrated_markers = ("frustrated", "again", "still not", "third time", "annoyed")
    if any(m in joined for m in angry_markers):
        return "angry"
    if any(m in joined for m in frustrated_markers):
        return "frustrated"
    return "neutral"
