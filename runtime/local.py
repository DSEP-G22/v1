"""Single-process demo entry point: intake API + all consumers + workspace API on one Uvicorn
process. `python -m runtime.local`."""

from __future__ import annotations

import atexit

import uvicorn

from runtime.wiring import build_app


def main() -> None:
    app = build_app()
    app.start()
    atexit.register(app.stop)

    uvicorn.run(app.combined_app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
