"""Wires services 1-6 directly against the in-process broker (no runtime/wiring.py yet) to prove
a ticket reaches AGGREGATED under the stub profile."""

from __future__ import annotations

import os
import time

os.environ["APP_PROFILE"] = "stub"

from libs.domain.contracts.events import Topics  # noqa: E402
from libs.platform.broker.inprocess import InProcessBroker  # noqa: E402
from libs.platform.config import get_settings  # noqa: E402
from libs.platform.db import outbox  # noqa: E402
from libs.platform.db.repositories import CustomerRepo, OrganizationRepo, TicketRepo, UnifiedPayloadRepo  # noqa: E402
from libs.platform.db.session import build_engine, init_db, session_scope  # noqa: E402
from libs.platform.registry import build_ports  # noqa: E402
from services.aggregator_svc.handler import handle_audio_done, handle_image_done, handle_text_done, sweep  # noqa: E402
from services.audio_svc.handler import handle as audio_handle  # noqa: E402
from services.image_svc.handler import handle as image_handle  # noqa: E402
from services.intake_api.handler import InboundFile, create_ticket  # noqa: E402
from services.routing_svc.handler import handle as routing_handle  # noqa: E402
from services.text_svc.handler import handle as text_handle  # noqa: E402

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 20
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def _drain_until_aggregated(broker: InProcessBroker, engine, ticket_id: str, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        outbox.drain(broker, engine)
        with session_scope(engine) as session:
            ticket = TicketRepo(session).get(ticket_id)
            if ticket is not None and ticket.state == "AGGREGATED":
                return
        time.sleep(0.05)
    raise AssertionError(f"ticket {ticket_id} did not reach AGGREGATED within {timeout_s}s")


def test_pipeline_reaches_aggregated(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "stub")
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "vectors.json"))
    get_settings.cache_clear()
    settings = get_settings()

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/pipeline.db")
    init_db(engine)
    ports = build_ports(settings)
    ports.object_store = type(ports.object_store)(root=tmp_path / "objects")

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Test Org")
        customer = CustomerRepo(session).create(org_id=org.id, name="Test Customer")
        customer_id = customer.id

    broker = InProcessBroker(max_retries=2)
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

        _drain_until_aggregated(broker, engine, ticket_id)

        with session_scope(engine) as session:
            payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
            assert payload is not None
            assert payload.partial is False
            assert "[CUSTOMER_TEXT]" in payload.fused_text
            assert "[AUDIO:" in payload.fused_text
            assert "[IMAGE:" in payload.fused_text
    finally:
        broker.stop()

    get_settings.cache_clear()


def test_sweep_finalizes_expired_partial_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "stub")
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "vectors2.json"))
    monkeypatch.setenv("AGGREGATION_WINDOW_S", "0")
    get_settings.cache_clear()
    settings = get_settings()

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/pipeline2.db")
    init_db(engine)
    ports = build_ports(settings)
    ports.object_store = type(ports.object_store)(root=tmp_path / "objects2")

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Test Org 2")
        customer = CustomerRepo(session).create(org_id=org.id, name="Test Customer 2")
        customer_id = customer.id

    broker = InProcessBroker(max_retries=1)
    broker.subscribe(Topics.TICKETS_RAW, "routing_svc", lambda env: routing_handle(ports, engine, settings, env))
    # Deliberately do NOT wire audio_svc — its attachment will never produce a done event, so
    # only the window sweep can close this ticket out as partial.
    broker.subscribe(Topics.TICKETS_TEXT_WORK, "text_svc", lambda env: text_handle(ports, engine, settings, env))
    broker.subscribe(
        Topics.TICKETS_TEXT_DONE, "aggregator_svc", lambda env: handle_text_done(ports, engine, settings, env)
    )
    broker.start()

    try:
        ticket_id = create_ticket(
            ports,
            engine,
            customer_id=customer_id,
            channel="web_portal",
            text="Hello, my line keeps dropping.",
            files=[InboundFile(filename="call.wav", data=WAV_HEADER)],
            idempotency_key=None,
        )

        deadline = time.time() + 5
        while time.time() < deadline:
            outbox.drain(broker, engine)
            time.sleep(0.05)

        sweep(ports, engine, settings)

        with session_scope(engine) as session:
            ticket = TicketRepo(session).get(ticket_id)
            assert ticket.state == "AGGREGATED"
            payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
            assert payload.partial is True
            assert "PARTIAL_PAYLOAD" in payload.flags
    finally:
        broker.stop()

    get_settings.cache_clear()
