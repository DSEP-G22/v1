from __future__ import annotations

from pathlib import Path
from typing import Protocol

from libs.domain.contracts.media import AudioTranscript


class TranscriberPort(Protocol):
    def transcribe(self, audio_path: Path, attachment_id: str) -> AudioTranscript: ...
