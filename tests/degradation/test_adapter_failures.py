"""The single most valuable test suite in the project (per the implementation plan): for each of
ASR, VLM, LLM, and the embedder, replace the adapter with one that always raises and assert the
ticket still reaches READY_FOR_AGENT with the expected degradation signal. This is what proves
G7 (graceful degradation)."""

from __future__ import annotations

import os
import time

import pytest

os.environ["APP_PROFILE"] = "stub"

from libs.domain.contracts.events import Topics  # noqa: E402
from libs.platform.broker.inprocess import InProcessBroker  # noqa: E402
from libs.platform.config import get_settings  # noqa: E402
from libs.platform.db import outbox  # noqa: E402
from libs.platform.db.repositories import (  # noqa: E402
    CustomerRepo,
    DiagnosisRepo,
    OrganizationRepo,
    TicketRepo,
    UnifiedPayloadRepo,
)
from libs.platform.db.session import build_engine, init_db, session_scope  # noqa: E402
from libs.platform.registry import build_ports  # noqa: E402
from services.aggregator_svc.handler import handle_audio_done, handle_image_done, handle_text_done, sweep  # noqa: E402
from services.audio_svc.handler import handle as audio_handle  # noqa: E402
from services.image_svc.handler import handle as image_handle  # noqa: E402
from services.intake_api.handler import InboundFile, create_ticket  # noqa: E402
from services.orchestrator_svc.handler import handle as orchestrator_handle  # noqa: E402
from services.projector_svc.handler import handle_ready as projector_handle  # noqa: E402
from services.response_svc.handler import handle as response_handle  # noqa: E402
from services.routing_svc.handler import handle as routing_handle  # noqa: E402
from services.text_svc.handler import handle as text_handle  # noqa: E402
from services.triage_svc.handler import handle as triage_handle  # noqa: E402

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 20
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class _AlwaysRaisingAdapter:
    def __getattr__(self, name: str):
        def _raise(*args, **kwargs):
            raise RuntimeError(f"simulated {name} failure")

        return _raise


def _wire_all_services(broker: InProcessBroker, ports, engine, settings) -> None:
    broker.subscribe(Topics.TICKETS_RAW, "routing_svc", lambda env: routing_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_TEXT_WORK, "text_svc", lambda env: text_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_AUDIO_WORK, "audio_svc", lambda env: audio_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_IMAGE_WORK, "image_svc", lambda env: image_handle(ports, engine, settings, env))
    broker.subscribe(
        Topics.TICKETS_TEXT_DONE, "aggregator_svc", lambda env: handle_text_done(ports, engine, settings, env)
    )
    broker.subscribe(
        Topics.TICKETS_AUDIO_DONE, "aggregator_svc", lambda env: handle_audio_done(ports, engine, settings, env)
    )
    broker.subscribe(
        Topics.TICKETS_IMAGE_DONE, "aggregator_svc", lambda env: handle_image_done(ports, engine, settings, env)
    )
    broker.subscribe(Topics.TICKETS_AGGREGATED, "triage_svc", lambda env: triage_handle(ports, engine, settings, env))
    broker.subscribe(
        Topics.TICKETS_TRIAGED, "orchestrator_svc", lambda env: orchestrator_handle(ports, engine, settings, env)
    )
    broker.subscribe(
        Topics.TICKETS_DIAGNOSED, "response_svc", lambda env: response_handle(ports, engine, settings, env)
    )
    broker.subscribe(Topics.TICKETS_READY, "projector_svc", lambda env: projector_handle(ports, engine, settings, env))


def _run_ticket_to_completion(tmp_path, monkeypatch, broken_port: str | None):
    monkeypatch.setenv("APP_PROFILE", "stub")
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "vectors.json"))
    monkeypatch.setenv("AGGREGATION_WINDOW_S", "2")
    get_settings.cache_clear()
    settings = get_settings()

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/pipeline.db")
    init_db(engine)
    ports = build_ports(settings)
    ports.object_store = type(ports.object_store)(root=tmp_path / "objects")

    if broken_port is not None:
        setattr(ports, broken_port, _AlwaysRaisingAdapter())

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Test Org")
        customer = CustomerRepo(session).create(org_id=org.id, name="Test Customer")
        customer_id = customer.id

    broker = InProcessBroker(max_retries=1)
    _wire_all_services(broker, ports, engine, settings)
    broker.start()

    try:
        ticket_id = create_ticket(
            ports,
            engine,
            customer_id=customer_id,
            channel="web_portal",
            text="My router's power light is red and internet is down.",
            files=[
                InboundFile(filename="call.wav", data=WAV_HEADER),
                InboundFile(filename="router.png", data=PNG_HEADER),
            ],
            idempotency_key=None,
        )

        deadline = time.time() + 20
        state = None
        while time.time() < deadline:
            outbox.drain(broker, engine)
            sweep(ports, engine, settings)
            with session_scope(engine) as session:
                ticket = TicketRepo(session).get(ticket_id)
                state = ticket.state if ticket else None
            if state in ("READY_FOR_AGENT", "FAILED"):
                break
            time.sleep(0.05)

        return ticket_id, state, engine
    finally:
        broker.stop()
        get_settings.cache_clear()


def test_baseline_reaches_ready_for_agent(tmp_path, monkeypatch):
    ticket_id, state, engine = _run_ticket_to_completion(tmp_path, monkeypatch, broken_port=None)
    assert state == "READY_FOR_AGENT"
    with session_scope(engine) as session:
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        assert payload.partial is False


def test_asr_failure_still_reaches_ready_for_agent(tmp_path, monkeypatch):
    ticket_id, state, engine = _run_ticket_to_completion(tmp_path, monkeypatch, broken_port="transcriber")
    assert state == "READY_FOR_AGENT"
    with session_scope(engine) as session:
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        assert payload.partial is True
        assert "PARTIAL_PAYLOAD" in payload.flags
        assert "[AUDIO:" not in payload.fused_text
        assert "[IMAGE:" in payload.fused_text


def test_vlm_failure_still_reaches_ready_for_agent(tmp_path, monkeypatch):
    ticket_id, state, engine = _run_ticket_to_completion(tmp_path, monkeypatch, broken_port="visual_extractor")
    assert state == "READY_FOR_AGENT"
    with session_scope(engine) as session:
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        assert payload.partial is True
        assert "PARTIAL_PAYLOAD" in payload.flags
        assert "[IMAGE:" not in payload.fused_text
        assert "[AUDIO:" in payload.fused_text


def test_llm_failure_still_reaches_ready_for_agent(tmp_path, monkeypatch):
    ticket_id, state, engine = _run_ticket_to_completion(tmp_path, monkeypatch, broken_port="text_generator")
    assert state == "READY_FOR_AGENT"
    with session_scope(engine) as session:
        diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
        assert diagnosis is not None
        assert diagnosis.needs_human_diagnosis is True
        assert diagnosis.fault is None


def test_embedder_failure_still_reaches_ready_for_agent(tmp_path, monkeypatch):
    ticket_id, state, engine = _run_ticket_to_completion(tmp_path, monkeypatch, broken_port="embedder")
    assert state == "READY_FOR_AGENT"
    with session_scope(engine) as session:
        diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
        assert diagnosis is not None
