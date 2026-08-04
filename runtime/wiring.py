"""Builds ports, DB, broker; subscribes every consumer handler to its topic/group; starts the
outbox drainer and the aggregation sweeper. `runtime/local.py` is the single-process demo entry
point built on top of this."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from libs.domain.contracts.events import Topics
from libs.platform.config import Settings, get_settings
from libs.platform.db import outbox
from libs.platform.db.session import build_engine, init_db
from libs.platform.dlq import install_dlq_capture
from libs.platform.registry import Ports, build_ports
from services.admin_api.app import build_app as build_admin_app
from services.aggregator_svc.handler import handle_audio_done, handle_image_done, handle_text_done, sweep
from services.audio_svc.handler import handle as audio_handle
from services.image_svc.handler import handle as image_handle
from services.intake_api.app import build_app as build_intake_app
from services.orchestrator_svc.handler import handle as orchestrator_handle
from services.projector_svc.handler import handle_ready as projector_handle
from services.response_svc.handler import handle as response_handle
from services.routing_svc.handler import handle as routing_handle
from services.text_svc.handler import handle as text_handle
from services.triage_svc.handler import handle as triage_handle
from services.workspace_api.app import build_app as build_workspace_app

OUTBOX_DRAIN_INTERVAL_S = 0.2
AGGREGATION_SWEEP_INTERVAL_S = 5.0


@dataclass
class App:
    settings: Settings
    engine: Engine
    ports: Ports
    intake_app: FastAPI
    workspace_app: FastAPI
    admin_app: FastAPI
    combined_app: FastAPI
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _threads: list[threading.Thread] = field(default_factory=list)

    def start(self) -> None:
        self.ports.event_broker.start()
        self._stop_event.clear()

        outbox_thread = threading.Thread(target=self._outbox_loop, daemon=True, name="outbox-drainer")
        sweep_thread = threading.Thread(target=self._sweep_loop, daemon=True, name="aggregation-sweeper")
        self._threads = [outbox_thread, sweep_thread]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=5)
        self.ports.event_broker.stop()

    def _outbox_loop(self) -> None:
        while not self._stop_event.is_set():
            outbox.drain(self.ports.event_broker, self.engine)
            self._stop_event.wait(OUTBOX_DRAIN_INTERVAL_S)

    def _sweep_loop(self) -> None:
        while not self._stop_event.is_set():
            sweep(self.ports, self.engine, self.settings)
            self._stop_event.wait(AGGREGATION_SWEEP_INTERVAL_S)

    def wait_forever(self) -> None:
        while True:
            time.sleep(1)


def build_app(settings: Settings | None = None) -> App:
    settings = settings or get_settings()
    engine = build_engine(settings.database_url)
    init_db(engine)
    ports = build_ports(settings)

    broker = ports.event_broker

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
    broker.subscribe(
        Topics.TICKETS_READY, "projector_svc", lambda env: projector_handle(ports, engine, settings, env)
    )
    install_dlq_capture(broker, engine)

    intake_app = build_intake_app(ports, engine)
    workspace_app = build_workspace_app(ports, engine, settings)
    admin_app = build_admin_app(ports, engine, settings)

    combined_app = FastAPI(title="cst-v1")
    _install_cors(combined_app, settings)
    combined_app.mount("/workspace", workspace_app)
    combined_app.mount("/admin", admin_app)
    # Mounted last and at the root, so the more specific prefixes above win.
    combined_app.mount("/", intake_app)

    return App(
        settings=settings,
        engine=engine,
        ports=ports,
        intake_app=intake_app,
        workspace_app=workspace_app,
        admin_app=admin_app,
        combined_app=combined_app,
    )


def _install_cors(app: FastAPI, settings: Settings) -> None:
    """The frontend is a separate deployable served from its own origin, so the browser sends a
    preflight before every non-GET call and blocks the response without these headers.

    `cors_allow_origins` is an explicit list, never `*`: credentials travel in the Authorization
    header, and a wildcard origin combined with credentials is exactly the configuration that
    lets any site read an authenticated response."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-Id", "Idempotency-Key"],
    )
