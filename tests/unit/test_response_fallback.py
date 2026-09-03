from __future__ import annotations

import json

from libs.domain.contracts.events import EventEnvelope
from libs.platform.config import get_settings
from libs.platform.models.asr import StubTranscriber
from libs.platform.models.llm import StubGenerator
from libs.platform.db.repositories import (
    CustomerRepo,
    DiagnosisRepo,
    DraftResponseRepo,
    OrganizationRepo,
    TicketRepo,
    UnifiedPayloadRepo,
)
from libs.platform.db.session import build_engine, init_db, session_scope
from libs.platform.registry import build_ports
from services.response_svc.handler import handle as response_handle


class _FailingGenerator:
    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("llm unavailable")


def test_response_fallback_marks_non_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "stub")
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "vectors.json"))
    get_settings.cache_clear()
    settings = get_settings()

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/pipeline.db")
    init_db(engine)
    ports = build_ports(settings)
    ports.text_generator = _FailingGenerator()

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Test Org")
        customer = CustomerRepo(session).create(org_id=org.id, name="Jane Doe")
        ticket = TicketRepo(session).create(
            org_id=org.id,
            customer_id=customer.id,
            channel="web_portal",
            state="DIAGNOSED",
            department="network_operations",
        )
        UnifiedPayloadRepo(session).create(
            ticket_id=ticket.id,
            revision=1,
            original_text="router red light",
            fused_text="router red light",
            provenance=[],
            flags=[],
            partial=False,
            payload_metadata={},
        )
        DiagnosisRepo(session).create(
            ticket_id=ticket.id,
            intent="report_fault",
            fault="fault_power_supply",
            confidence=0.9,
            alternatives=[],
            rationale="test diagnosis",
            needs_human_diagnosis=False,
            citations=[],
        )
        ticket_id = ticket.id

    response_handle(
        ports,
        engine,
        settings,
        EventEnvelope(event_id=f"diagnosed-{ticket_id}", ticket_id=ticket_id, stage="orchestrator_svc", body={}),
    )

    with session_scope(engine) as session:
        draft = DraftResponseRepo(session).get_latest(ticket_id)
        ticket = TicketRepo(session).get(ticket_id)

    assert draft is not None
    assert draft.ai_text == "Hi, thanks for reaching out, we're looking into this now."
    assert draft.ai_generated is False
    assert ticket is not None
    assert ticket.state == "READY_FOR_AGENT"

    get_settings.cache_clear()


def test_stub_transcriber_does_not_invent_customer_claim(tmp_path):
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"stub audio")

    transcript = StubTranscriber().transcribe(audio_path, "attachment-1")

    assert "working properly" not in transcript.text.lower()
    assert "transcript unavailable" in transcript.text.lower()
    assert transcript.attachment_id == "attachment-1"


def test_stub_generator_does_not_fabricate_issue_details():
    raw = StubGenerator().generate("router keeps disconnecting and red power light", prompt_kind="draft")
    payload = json.loads(raw)

    assert payload["ai_text"]
    assert "red" not in payload["ai_text"].lower()
    assert "power light" not in payload["ai_text"].lower()
    assert "reviewing" in payload["ai_text"].lower()
