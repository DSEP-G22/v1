"""Static bearer token per role (v1 auth stand-in, enough to exercise authorization checks
without building an IdP). Each token maps to a role; the actor used for `agent_decision.actor_id`
is the first seeded `app_user` with that role. Shared by workspace_api and admin_api, lives in
the platform layer (not a `services/*` package) so importing it isn't a cross-service import."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException
from sqlalchemy.engine import Engine

from libs.platform.config import Settings
from libs.platform.db.repositories import AppUserRepo
from libs.platform.db.session import session_scope

ROLE_AGENT = "agent"
ROLE_LEAD = "lead"
ROLE_ADMIN = "admin"


@dataclass
class CurrentUser:
    user_id: str
    username: str
    role: str


def _role_for_token(settings: Settings, token: str) -> str | None:
    if token == settings.auth_token_agent:
        return ROLE_AGENT
    if token == settings.auth_token_lead:
        return ROLE_LEAD
    if token == settings.auth_token_admin:
        return ROLE_ADMIN
    return None


def resolve_user_for_token(settings: Settings, engine: Engine, token: str) -> CurrentUser | None:
    """Token -> user, or None. Shared by the HTTP dependency and the WebSocket handshake, which
    cannot send an Authorization header and passes the token as a query parameter instead."""
    role = _role_for_token(settings, token.strip())
    if role is None:
        return None

    with session_scope(engine) as session:
        for candidate_username in _candidates_for_role(role):
            user = AppUserRepo(session).get_by_username(candidate_username)
            if user is not None:
                return CurrentUser(user_id=user.id, username=user.username, role=user.role)
    return None


def make_current_user_dependency(settings: Settings, engine: Engine):
    def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
        if not authorization or not authorization.lower().startswith("bearer "):
            # UI-1: the message never distinguishes "unknown account" from "wrong credentials".
            raise HTTPException(status_code=401, detail="not authenticated")
        token = authorization.split(" ", 1)[1]
        user = resolve_user_for_token(settings, engine, token)
        if user is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        return user

    return get_current_user


def _candidates_for_role(role: str) -> list[str]:
    return [f"{role}1", role]


def require_role(user: CurrentUser, *allowed_roles: str) -> None:
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail=f"role {user.role} may not perform this action")
