"""Sniffs file type from magic bytes, never trust the declared MIME type / filename."""

from __future__ import annotations

from libs.domain.enums import Modality

_SIGNATURES: list[tuple[bytes, int, str, Modality]] = [
    (b"RIFF", 0, "audio/wav", Modality.audio), # WAVE has "WAVE" at offset 8, checked separately
    (b"ID3", 0, "audio/mpeg", Modality.audio),
    (b"\xff\xfb", 0, "audio/mpeg", Modality.audio),
    (b"\xff\xf3", 0, "audio/mpeg", Modality.audio),
    (b"OggS", 0, "audio/ogg", Modality.audio),
    (b"fLaC", 0, "audio/flac", Modality.audio),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png", Modality.image),
    (b"\xff\xd8\xff", 0, "image/jpeg", Modality.image),
    (b"GIF87a", 0, "image/gif", Modality.image),
    (b"GIF89a", 0, "image/gif", Modality.image),
    (b"BM", 0, "image/bmp", Modality.image),
]


class UnsupportedMediaType(ValueError):
    pass


def sniff_media(data: bytes) -> tuple[str, Modality]:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav", Modality.audio

    for signature, offset, content_type, modality in _SIGNATURES:
        if signature == b"RIFF":
            continue  # handled above with the WAVE check
        if data[offset : offset + len(signature)] == signature:
            return content_type, modality

    raise UnsupportedMediaType("could not identify file type from magic bytes")
