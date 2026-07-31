from __future__ import annotations

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.engine import Engine

from libs.platform.registry import Ports
from services.intake_api.handler import (
    DuplicateIdempotencyKey,
    InboundFile,
    TicketCreationError,
    create_ticket,
    get_status,
)


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

    return app
