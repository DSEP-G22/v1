from __future__ import annotations

import threading
import time

from libs.domain.contracts.events import Topics
from libs.platform.config import get_settings
from libs.platform.db.session import build_engine, init_db
from libs.platform.registry import build_ports
from services.aggregator_svc.handler import handle_audio_done, handle_image_done, handle_text_done, sweep


def _sweeper_loop(ports, engine, settings, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        sweep(ports, engine, settings)
        stop_event.wait(5)


def main() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    init_db(engine)
    ports = build_ports(settings)

    ports.event_broker.subscribe(
        Topics.TICKETS_TEXT_DONE, "aggregator_svc", lambda env: handle_text_done(ports, engine, settings, env)
    )
    ports.event_broker.subscribe(
        Topics.TICKETS_AUDIO_DONE, "aggregator_svc", lambda env: handle_audio_done(ports, engine, settings, env)
    )
    ports.event_broker.subscribe(
        Topics.TICKETS_IMAGE_DONE, "aggregator_svc", lambda env: handle_image_done(ports, engine, settings, env)
    )
    ports.event_broker.start()

    stop_event = threading.Event()
    sweeper = threading.Thread(target=_sweeper_loop, args=(ports, engine, settings, stop_event), daemon=True)
    sweeper.start()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
