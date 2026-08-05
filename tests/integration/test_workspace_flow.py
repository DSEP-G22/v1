"""End-to-end through workspace_api: ticket reaches READY_FOR_AGENT, an agent locks it, approves
it, and delivery_gateway records a delivery whose approval_id is a real agent_decision.id."""

from __future__ import annotations

import os
import time

os.environ["APP_PROFILE"] = "stub"

from fastapi.testclient import TestClient  # noqa: E402

from libs.domain.contracts.events import Topics  # noqa: E402
from libs.platform.broker.inprocess import InProcessBroker  # noqa: E402
from libs.platform.config import get_settings  # noqa: E402
from libs.platform.db import outbox  # noqa: E402
from libs.platform.db.repositories import (  # noqa: E402
    AppUserRepo,
    CustomerRepo,
    DeliveryRepo,
    OrganizationRepo,
    TicketRepo,
)
from libs.platform.db.session import build_engine, init_db, session_scope  # noqa: E402
from libs.platform.registry import build_ports  # noqa: E402
from services.aggregator_svc.handler import handle_audio_done, handle_image_done, handle_text_done  # noqa: E402
from services.audio_svc.handler import handle as audio_handle  # noqa: E402
from services.image_svc.handler import handle as image_handle  # noqa: E402
from services.intake_api.handler import InboundFile, create_ticket  # noqa: E402
from services.orchestrator_svc.handler import handle as orchestrator_handle  # noqa: E402
from services.projector_svc.handler import handle_ready as projector_handle  # noqa: E402
from services.response_svc.handler import handle as response_handle  # noqa: E402
from services.routing_svc.handler import handle as routing_handle  # noqa: E402
from services.text_svc.handler import handle as text_handle  # noqa: E402
from services.triage_svc.handler import handle as triage_handle  # noqa: E402
from services.workspace_api.app import build_app as build_workspace_app

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 20
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def test_lock_approve_delivers(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "stub")
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "vectors.json"))
    monkeypatch.setenv("AUTH_TOKEN_AGENT", "test-agent-token")
    get_settings.cache_clear()
    settings = get_settings()

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/pipeline.db")
    init_db(engine)
    ports = build_ports(settings)
    ports.object_store = type(ports.object_store)(root=tmp_path / "objects")

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Test Org")
        AppUserRepo(session).create(org_id=org.id, username="agent1", role="agent", email="a@example.com")
        customer = CustomerRepo(session).create(org_id=org.id, name="Jane Doe", email="jane@example.com")
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
    broker.subscribe(Topics.TICKETS_AGGREGATED, "triage_svc", lambda env: triage_handle(ports, engine, settings, env))
    broker.subscribe(
        Topics.TICKETS_TRIAGED, "orchestrator_svc", lambda env: orchestrator_handle(ports, engine, settings, env)
    )
    broker.subscribe(
        Topics.TICKETS_DIAGNOSED, "response_svc", lambda env: response_handle(ports, engine, settings, env)
    )
    broker.subscribe(Topics.TICKETS_READY, "projector_svc", lambda env: projector_handle(ports, engine, settings, env))
    broker.start()

    try:
        ticket_id = create_ticket(
            ports,
            engine,
            customer_id=customer_id,
            channel="web_portal",
            text="My router's power light is red and internet is down.",
            files=[InboundFile(filename="call.wav", data=WAV_HEADER), InboundFile(filename="router.png", data=PNG_HEADER)],
            idempotency_key=None,
        )

        deadline = time.time() + 15
        while time.time() < deadline:
            outbox.drain(broker, engine)
            with session_scope(engine) as session:
                ticket = TicketRepo(session).get(ticket_id)
                if ticket is not None and ticket.state == "READY_FOR_AGENT":
                    break
            time.sleep(0.05)
        else:
            raise AssertionError("ticket did not reach READY_FOR_AGENT")

        app = build_workspace_app(ports, engine, settings)
        client = TestClient(app)
        headers = {"Authorization": "Bearer test-agent-token"}

        resp = client.post(f"/tickets/{ticket_id}/lock", headers=headers)
        assert resp.status_code == 200, resp.text

        with session_scope(engine) as session:
            ticket = TicketRepo(session).get(ticket_id)
            assert ticket.state == "IN_REVIEW"

        resp = client.post(f"/tickets/{ticket_id}/approve", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["approval_id"]
        assert body["status"] == "SENT"

        with session_scope(engine) as session:
            ticket = TicketRepo(session).get(ticket_id)
            assert ticket.state == "RESOLVED"

        with session_scope(engine) as session:
            from libs.platform.db.models import DeliveryRow
            from sqlalchemy import select

            delivery = session.execute(select(DeliveryRow).where(DeliveryRow.ticket_id == ticket_id)).scalar_one()
            assert delivery.approval_id == body["approval_id"]
            assert delivery.status == "SENT"
    finally:
        broker.stop()
        get_settings.cache_clear()
