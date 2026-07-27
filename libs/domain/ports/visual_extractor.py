from __future__ import annotations

from pathlib import Path
from typing import Protocol

from libs.domain.contracts.media import VisualSummary


class VisualExtractorPort(Protocol):
    def extract(self, image_path: Path, attachment_id: str, template: str) -> VisualSummary: ...
