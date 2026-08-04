from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from fastapi import File, Form, UploadFile

from libs.platform.auth import CurrentUser, ROLE_ADMIN, make_current_user_dependency, require_role
from libs.platform.config import Settings
from libs.platform.registry import Ports
from services.admin_api.handler import (
    create_user,
    get_model_registry,
    get_routing_rules,
    get_thresholds,
    health,
    ingest_uploaded_document,
    list_action_registry,
    list_dlq,
    list_knowledge_documents,
    list_users,
    put_routing_rules,
    replay_dlq_entry,
    search_knowledge,
    upsert_action_registry_entry,
)


class UserCreate(BaseModel):
    org_id: str
    username: str
    role: str
    email: str | None = None


class ActionRegistryEntryUpsert(BaseModel):
    department: str
    description: str
    mapped_faults: list[str] = []
    requires_supervisor: bool = False
    enabled: bool = True
    requires_fields: list[str] = []
    impact_limits: dict[str, float] = {}


class RoutingRulesUpdate(BaseModel):
    rules: list[dict]


def build_app(ports: Ports, engine: Engine, settings: Settings) -> FastAPI:
    app = FastAPI(title="admin_api")
    get_current_user = make_current_user_dependency(settings, engine)

    def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        require_role(user, ROLE_ADMIN)
        return user

    @app.get("/health")
    def get_health() -> dict:
        return health()

    @app.post("/users")
    def post_user(body: UserCreate, user: CurrentUser = Depends(require_admin)) -> dict:
        return create_user(
            engine, org_id=body.org_id, username=body.username, role=body.role, email=body.email, changed_by=user.user_id
        )

    @app.get("/action-registry")
    def get_action_registry(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
        return list_action_registry(engine)

    @app.put("/action-registry/{action_id}")
    def put_action_registry_entry(
        action_id: str, body: ActionRegistryEntryUpsert, user: CurrentUser = Depends(require_admin)
    ) -> dict:
        return upsert_action_registry_entry(engine, action_id=action_id, changed_by=user.user_id, **body.model_dump())

    @app.get("/routing-rules")
    def get_routing_rules_endpoint(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
        return get_routing_rules()

    @app.put("/routing-rules")
    def put_routing_rules_endpoint(body: RoutingRulesUpdate, user: CurrentUser = Depends(require_admin)) -> dict:
        return put_routing_rules(engine, rules=body.rules, changed_by=user.user_id)

    @app.get("/thresholds")
    def get_thresholds_endpoint(user: CurrentUser = Depends(get_current_user)) -> dict:
        return get_thresholds(settings)

    @app.get("/users")
    def get_users(user: CurrentUser = Depends(require_admin)) -> list[dict]:
        return list_users(engine)

    @app.get("/models")
    def get_models(user: CurrentUser = Depends(get_current_user)) -> dict:
        return get_model_registry(settings)

    @app.get("/knowledge/documents")
    def get_knowledge_documents(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
        return list_knowledge_documents(engine)

    @app.post("/knowledge/documents", status_code=201)
    async def post_knowledge_document(
        org_id: str = Form(...),
        file: UploadFile = File(...),
        user: CurrentUser = Depends(require_admin),
    ) -> dict:
        data = await file.read()
        try:
            return ingest_uploaded_document(
                ports, engine, org_id=org_id, filename=file.filename or "upload.md", data=data
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/knowledge/search")
    def get_knowledge_search(q: str, k: int = 5, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
        return search_knowledge(ports, q, k=k)

    @app.get("/dlq")
    def get_dlq(user: CurrentUser = Depends(require_admin)) -> list[dict]:
        return list_dlq(engine)

    @app.post("/dlq/{entry_id}/replay")
    def post_dlq_replay(entry_id: str, user: CurrentUser = Depends(require_admin)) -> dict:
        try:
            return replay_dlq_entry(engine, ports.event_broker, entry_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
