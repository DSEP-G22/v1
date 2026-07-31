from __future__ import annotations

import uvicorn

from libs.platform.config import get_settings
from libs.platform.db.session import build_engine, init_db
from libs.platform.registry import build_ports
from services.intake_api.app import build_app


def main() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    init_db(engine)
    ports = build_ports(settings)
    app = build_app(ports, engine)
    uvicorn.run(app, host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
