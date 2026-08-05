"""Step 8 acceptance: full pipeline under the stub profile with the in-process broker.
Ticket in -> READY_FOR_AGENT out."""

from __future__ import annotations

import os
import time

os.environ["APP_PROFILE"] = "stub"

from libs.domain.contracts.events import Topics  # noqa: E402
from libs.platform.broker.inprocess import InProcessBroker  # noqa: E402
from libs.platform.config import get_settings  # noqa: E402
from libs.platform.db import outbox  # noqa: E402
from libs.platform.db.repositories import (  # noqa: E402
    CustomerRepo,
    DraftResponseRepo,
    OrganizationRepo,
    QueueProjectionRepo,
    TicketRepo,
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


def _drain_until(engine, broker, ticket_id: str, target_state: str, timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        outbox.drain(broker, engine)
        with session_scope(engine) as session:
            ticket = TicketRepo(session).get(ticket_id)
            if ticket is not None and ticket.state == target_state:
                return
        time.sleep(0.05)
    raise AssertionError(f"ticket {ticket_id} did not reach {target_state} within {timeout_s}s")


def test_pipeline_reaches_ready_for_agent(tmp_path, monkeypatch):
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
        customer = CustomerRepo(session).create(org_id=org.id, name="Jane Doe")
        customer_id = customer.id

    broker = InProcessBroker(max_retries=2)
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

        _drain_until(engine, broker, ticket_id, "READY_FOR_AGENT")

        with session_scope(engine) as session:
            draft = DraftResponseRepo(session).get_latest(ticket_id)
            assert draft is not None
            assert draft.ai_text

        # response_svc's tickets.ready event and projector_svc's async handling of it can
        # still be in flight the instant ticket.state flips to READY_FOR_AGENT; poll briefly.
        deadline = time.time() + 5.0
        projection = None
        while time.time() < deadline:
            outbox.drain(broker, engine)
            with session_scope(engine) as session:
                projection = QueueProjectionRepo(session).get(ticket_id)
            if projection is not None:
                break
            time.sleep(0.05)

        assert projection is not None
        assert projection.state == "READY_FOR_AGENT"
    finally:
        broker.stop()

    get_settings.cache_clear()
