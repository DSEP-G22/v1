from __future__ import annotations

import time

from libs.domain.contracts.events import Topics
from libs.platform.config import get_settings
from libs.platform.db.session import build_engine, init_db
from libs.platform.registry import build_ports
from services.projector_svc.handler import handle_ready


def main() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    init_db(engine)
    ports = build_ports(settings)

    ports.event_broker.subscribe(
        Topics.TICKETS_READY, "projector_svc", lambda env: handle_ready(ports, engine, settings, env)
    )
    ports.event_broker.start()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
