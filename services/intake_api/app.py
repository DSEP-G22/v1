from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.engine import Engine

from libs.platform.registry import Ports
from services.intake_api.handler import (
    DuplicateIdempotencyKey,
    InboundFile,
    TicketCreationError,
    create_ticket,
    get_status,
)

# Sample utterances for the submission page, written by
# `python -m evaluation.datasets.hf_audio` (see the CLI at the foot of that module). They are
# served from disk rather than bundled into the frontend because they are regenerable data, not
# source: ~3.4 MB of WAV that would otherwise sit in the repository and in every UI image.
_SAMPLE_AUDIO_DIR = Path(__file__).resolve().parents[2] / "v1_data" / "sample_audio"


def _intent_from_stem(stem: str) -> str:
    """`minds14_high_value_payment_0010` -> `high_value_payment`."""
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0] == "minds14" and parts[-1].isdigit():
        return "_".join(parts[1:-1])
    return stem


def _sample_files() -> dict[str, Path]:
    if not _SAMPLE_AUDIO_DIR.is_dir():
        return {}
    return {path.stem: path for path in sorted(_SAMPLE_AUDIO_DIR.glob("*.wav"))}


def build_app(ports: Ports, engine: Engine) -> FastAPI:
    app = FastAPI(title="intake_api")

    @app.post("/api/v1/tickets", status_code=202)
    async def post_ticket(
        customer_id: str = Form(...),
        channel: str = Form(...),
        text: str = Form(""),
        files: list[UploadFile] = File(default=[]),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        inbound_files = [InboundFile(filename=f.filename or "upload", data=await f.read()) for f in files]
        try:
            ticket_id = create_ticket(
                ports,
                engine,
                customer_id=customer_id,
                channel=channel,
                text=text,
                files=inbound_files,
                idempotency_key=idempotency_key,
            )
        except DuplicateIdempotencyKey as exc:
            return {"ticket_id": exc.ticket_id}
        except TicketCreationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ticket_id": ticket_id}

    @app.get("/api/v1/tickets/{ticket_id}/status")
    def get_ticket_status(ticket_id: str) -> dict:
        status = get_status(engine, ticket_id)
        if status is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        return status

    @app.get("/api/v1/sample-audio")
    def list_sample_audio() -> list[dict]:
        """Sample utterances the submission page offers, so testing does not mean attaching the
        same clip to every ticket. Empty when the directory has not been generated, which the UI
        renders as the picker simply being absent."""
        return [
            # The filename is minds14_<intent>_<index>, and the intent itself contains
            # underscores ("app_error", "high_value_payment"), so the label is everything between
            # the first prefix and the trailing index rather than a single split component.
            {"id": stem, "intent": _intent_from_stem(stem), "bytes": path.stat().st_size}
            for stem, path in _sample_files().items()
        ]

    @app.get("/api/v1/sample-audio/{sample_id}")
    def get_sample_audio(sample_id: str) -> FileResponse:
        # Looked up in the whitelist built from the directory listing rather than joined onto the
        # path, so a traversal attempt in `sample_id` cannot escape the directory.
        path = _sample_files().get(sample_id)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown sample")
        return FileResponse(path, media_type="audio/wav", filename=f"{sample_id}.wav")

    return app
