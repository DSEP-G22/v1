from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from libs.platform.auth import (
    ROLE_ADMIN,
    ROLE_LEAD,
    CurrentUser,
    make_current_user_dependency,
    resolve_user_for_token,
    require_role,
)
from libs.platform.config import Settings
from libs.platform.registry import Ports
from services.workspace_api.handler import (
    Conflict,
    NotFound,
    approve_and_send,
    dashboard_metrics,
    escalate_ticket,
    execute_action,
    get_attachment_bytes,
    get_ticket_detail,
    list_queue,
    lock_ticket,
    reassign_ticket,
    reject_draft,
    update_draft,
)


class DraftUpdate(BaseModel):
    current_text: str


class RejectBody(BaseModel):
    reason_code: str | None = None


class ReassignBody(BaseModel):
    department: str
    reason_code: str | None = None


class EscalateBody(BaseModel):
    reason_code: str | None = None


def build_app(ports: Ports, engine: Engine, settings: Settings) -> FastAPI:
    app = FastAPI(title="workspace_api")
    get_current_user = make_current_user_dependency(settings, engine)

    @app.get("/me")
    def get_me(user: CurrentUser = Depends(get_current_user)) -> dict:
        """UI-1: the login screen exchanges a token for the identity behind it. A wrong token
        returns 401 with a generic message, it never discloses whether a user exists."""
        return {"user_id": user.user_id, "username": user.username, "role": user.role}

    @app.get("/queue")
    def get_queue(department: str | None = None, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
        return list_queue(engine, department=department)

    @app.get("/dashboard")
    def get_dashboard(user: CurrentUser = Depends(get_current_user)) -> dict:
        require_role(user, ROLE_LEAD, ROLE_ADMIN)
        return dashboard_metrics(engine)

    @app.get("/tickets/{ticket_id}")
    def get_ticket(ticket_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
        try:
            return get_ticket_detail(engine, ticket_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tickets/{ticket_id}/attachments/{attachment_id}/content")
    def get_attachment(
        ticket_id: str, attachment_id: str, user: CurrentUser = Depends(get_current_user)
    ) -> Response:
        try:
            data, content_type, filename = get_attachment_bytes(ports, engine, ticket_id, attachment_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=data,
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    @app.post("/tickets/{ticket_id}/lock")
    def post_lock(ticket_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
        try:
            lock_ticket(engine, ticket_id, user.username)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"locked_by": user.username}

    @app.patch("/tickets/{ticket_id}/draft")
    def patch_draft(ticket_id: str, body: DraftUpdate, user: CurrentUser = Depends(get_current_user)) -> dict:
        try:
            return update_draft(engine, ticket_id, body.current_text)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tickets/{ticket_id}/approve")
    def post_approve(ticket_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
        try:
            return approve_and_send(ports, engine, settings, ticket_id=ticket_id, actor_id=user.user_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tickets/{ticket_id}/reject")
    def post_reject(ticket_id: str, body: RejectBody, user: CurrentUser = Depends(get_current_user)) -> dict:
        return reject_draft(engine, ticket_id, user.user_id, body.reason_code)

    @app.post("/tickets/{ticket_id}/reassign")
    def post_reassign(ticket_id: str, body: ReassignBody, user: CurrentUser = Depends(get_current_user)) -> dict:
        try:
            return reassign_ticket(engine, ticket_id, user.user_id, body.department, body.reason_code)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tickets/{ticket_id}/escalate")
    def post_escalate(ticket_id: str, body: EscalateBody, user: CurrentUser = Depends(get_current_user)) -> dict:
        try:
            return escalate_ticket(engine, ticket_id, user.user_id, body.reason_code)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tickets/{ticket_id}/actions/{rec_id}/execute")
    def post_execute_action(ticket_id: str, rec_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
        require_role(user, ROLE_LEAD, ROLE_ADMIN)
        try:
            return execute_action(ports, engine, ticket_id=ticket_id, recommendation_id=rec_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.websocket("/ws/queue")
    async def ws_queue(websocket: WebSocket) -> None:
        """UI-2 live queue. Browsers cannot set an Authorization header on a WebSocket, so the
        token arrives as a query parameter; it is validated exactly as the HTTP dependency does
        and the socket is closed with 1008 when it does not resolve to a user."""
        token = websocket.query_params.get("token", "")
        if resolve_user_for_token(settings, engine, token) is None:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        last = None
        try:
            while True:
                current = list_queue(engine)
                if current != last:
                    await websocket.send_json(current)
                    last = current
                # The in-process broker gives no change feed, so the socket polls the projection
                # and pushes only on change. The client still sees updates within ~2 s (REQ-WKS-2
                # allows 5 s) without a per-client refetch storm.
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            pass
        except RuntimeError:
            # receive after close during shutdown
            pass

    return app
