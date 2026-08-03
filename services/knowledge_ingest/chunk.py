"""Heading-aware chunking (~800 chars, 100 overlap). Splits Markdown on `#`-headings first so a
chunk boundary never falls mid-procedure, then further splits any section still longer than
`chunk_size` using a sliding window with overlap."""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _split_by_heading(text: str) -> list[str]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [text]

    sections: list[str] = []
    if matches[0].start() > 0:
        sections.append(text[: matches[0].start()])

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(text[match.start() : end])

    return [s for s in sections if s.strip()]


def _sliding_window(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    step = max(chunk_size - overlap, 1)
    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def heading_aware_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks: list[str] = []
    for section in _split_by_heading(text):
        chunks.extend(_sliding_window(section, chunk_size, overlap))
    return [c for c in chunks if c.strip()]
