"""Text normalisation, language detection, and PII scanning for the customer's original text.
No table ownership — this is a stateless transform between tickets.text.work and
tickets.text.done; the normalised text and flags flow through the event body."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.domain.enums import FlagCode
from libs.platform.config import Settings
from libs.platform.db import outbox
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports

_QUOTED_REPLY_MARKERS = re.compile(
    r"(^On .+wrote:$)|(^-{2,}\s*Original Message\s*-{2,}$)|(^From:.+$)", re.IGNORECASE | re.MULTILINE
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_NIC = re.compile(r"\b\d{9}[vVxX]\b|\b\d{12}\b")

_SINHALA_RANGE = range(0x0D80, 0x0DFF)
_TAMIL_RANGE = range(0x0B80, 0x0BFF)


def _strip_quoted_reply(text: str) -> str:
    match = _QUOTED_REPLY_MARKERS.search(text)
    if match:
        text = text[: match.start()]
    lines = [line for line in text.splitlines() if not line.strip().startswith(">")]
    return "\n".join(lines)


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _strip_quoted_reply(normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def detect_language(text: str) -> str:
    for ch in text:
        codepoint = ord(ch)
        if codepoint in _SINHALA_RANGE:
            return "si"
        if codepoint in _TAMIL_RANGE:
            return "ta"
    return "en"


def scan_pii(text: str) -> list[str]:
    flags: list[str] = []
    if _EMAIL.search(text) or _PHONE.search(text) or _CARD.search(text) or _NIC.search(text):
        flags.append(FlagCode.PII_DETECTED.value)
    return flags


def handle(ports: Ports, engine: Engine, settings: Settings, envelope: EventEnvelope) -> None:
    ticket_id = envelope.ticket_id
    original_text = envelope.body.get("original_text", "")

    normalized_text = normalize(original_text)
    language = detect_language(normalized_text)
    flags = scan_pii(normalized_text)

    with session_scope(engine) as session:
        outbox.enqueue(
            session,
            Topics.TICKETS_TEXT_DONE,
            ticket_id,
            EventEnvelope(
                event_id=f"text-done-{ticket_id}",
                ticket_id=ticket_id,
                stage="text_svc",
                body={"normalized_text": normalized_text, "language": language, "flags": flags, "status": "done"},
            ),
        )
