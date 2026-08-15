"""Users, routing rules, action registry CRUD, health, DLQ listing and replay. Every mutation
writes a config_version row."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.engine import Engine

from libs.domain.contracts.events import EventEnvelope
from libs.domain.ports.event_broker import EventBrokerPort
from libs.platform.config import Settings
from libs.platform.db.repositories import (
    ActionRegistryEntryRepo,
    AppUserRepo,
    ConfigVersionRepo,
    DlqEntryRepo,
    KnowledgeChunkRepo,
    KnowledgeDocumentRepo,
)
from libs.platform.db.session import session_scope
from libs.platform.registry import Ports
from services.knowledge_ingest.handler import ingest_path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTING_RULES_PATH = _REPO_ROOT / "config" / "routing_rules.yaml"


def _next_version(session, entity_type: str, entity_id: str) -> int:
    from sqlalchemy import func, select

    from libs.platform.db.models import ConfigVersionRow

    current_max = session.execute(
        select(func.max(ConfigVersionRow.version)).where(
            ConfigVersionRow.entity_type == entity_type, ConfigVersionRow.entity_id == entity_id
        )
    ).scalar_one()
    return (current_max or 0) + 1


def create_user(engine: Engine, *, org_id: str, username: str, role: str, email: str | None, changed_by: str) -> dict:
    with session_scope(engine) as session:
        user = AppUserRepo(session).create(org_id=org_id, username=username, role=role, email=email)
        version = _next_version(session, "app_user", user.id)
        ConfigVersionRepo(session).create(
            entity_type="app_user",
            entity_id=user.id,
            version=version,
            data={"username": username, "role": role, "email": email},
            changed_by=changed_by,
        )
        return {"user_id": user.id, "version": version}


def list_action_registry(engine: Engine) -> list[dict]:
    with session_scope(engine) as session:
        rows = ActionRegistryEntryRepo(session).list_all()
        return [
            {
                "action_id": r.action_id,
                "department": r.department,
                "description": r.description,
                "mapped_faults": r.mapped_faults,
                "requires_supervisor": r.requires_supervisor,
                "enabled": r.enabled,
                "requires_fields": r.requires_fields,
                "impact_limits": r.impact_limits,
            }
            for r in rows
        ]


def upsert_action_registry_entry(engine: Engine, *, action_id: str, changed_by: str, **fields: Any) -> dict:
    with session_scope(engine) as session:
        row = ActionRegistryEntryRepo(session).upsert(action_id, **fields)
        version = _next_version(session, "action_registry_entry", action_id)
        ConfigVersionRepo(session).create(
            entity_type="action_registry_entry",
            entity_id=action_id,
            version=version,
            data=fields,
            changed_by=changed_by,
        )
        return {"action_id": row.action_id, "version": version}


def get_routing_rules() -> list[dict]:
    if not _ROUTING_RULES_PATH.exists():
        return []
    data = yaml.safe_load(_ROUTING_RULES_PATH.read_text(encoding="utf-8")) or {}
    return data.get("rules", [])


def put_routing_rules(engine: Engine, *, rules: list[dict], changed_by: str) -> dict:
    _ROUTING_RULES_PATH.write_text(yaml.safe_dump({"rules": rules}, sort_keys=False), encoding="utf-8")

    with session_scope(engine) as session:
        version = _next_version(session, "routing_rules", "global")
        ConfigVersionRepo(session).create(
            entity_type="routing_rules", entity_id="global", version=version, data={"rules": rules}, changed_by=changed_by
        )
        return {"version": version, "rule_count": len(rules)}


def get_thresholds(settings: Settings) -> dict:
    """Read-only: hot-reloading pydantic-settings safely is out of scope for v1, changing a
    threshold requires editing .env and restarting."""
    return {
        "asr_low_confidence_threshold": settings.asr_low_confidence_threshold,
        "vlm_low_confidence_threshold": settings.vlm_low_confidence_threshold,
        "diagnosis_min_confidence": settings.diagnosis_min_confidence,
        "aggregation_window_s": settings.aggregation_window_s,
    }


def list_users(engine: Engine) -> list[dict]:
    with session_scope(engine) as session:
        return [
            {"id": u.id, "username": u.username, "role": u.role, "email": u.email, "org_id": u.org_id}
            for u in AppUserRepo(session).list_all()
        ]


def get_model_registry(settings: Settings) -> dict:
    """UI-5 model-version panel. Reports what `config/registry.yaml` declares next to what the
    running process actually resolved, because the two diverge whenever an adapter falls back."""
    registry_path = _REPO_ROOT / "config" / "registry.yaml"
    declared = yaml.safe_load(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    return {
        "declared": declared or {},
        "active": {
            "profile": settings.profile,
            "asr_impl": settings.asr_impl,
            "asr_model": settings.asr_model,
            "vlm_impl": settings.vlm_impl,
            "vlm_model": settings.vlm_model,
            "llm_impl": settings.llm_impl,
            "llm_model": settings.llm_model,
            "embedder_impl": settings.embedder_impl,
            "embedding_model": settings.embedding_model,
        },
    }


def list_knowledge_documents(engine: Engine) -> list[dict]:
    with session_scope(engine) as session:
        doc_repo = KnowledgeDocumentRepo(session)
        chunk_repo = KnowledgeChunkRepo(session)
        return [
            {
                "id": d.id,
                "title": d.title,
                "doc_type": d.doc_type,
                "source_path": d.source_path,
                "created_at": d.created_at.isoformat(),
                "chunk_count": len(chunk_repo.list_for_document(d.id)),
            }
            for d in doc_repo.list_all()
        ]


def ingest_uploaded_document(
    ports: Ports, engine: Engine, *, org_id: str, filename: str, data: bytes
) -> dict:
    """UI-6 SOP upload. The bytes are written to the configured knowledge directory first so an
    ingested document can be re-parsed later without the operator re-uploading it."""
    target_dir = _REPO_ROOT / "config" / "seed" / "knowledge"
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".md", ".txt", ".pdf"}:
        raise ValueError(f"unsupported document type '{suffix}' (expected .md, .txt or .pdf)")

    path = target_dir / Path(filename).name
    path.write_bytes(data)

    report = ingest_path(ports, engine, org_id=org_id, path=path)
    return {
        "document_id": report.document_id,
        "title": report.title,
        "num_chunks": report.num_chunks,
        "avg_chunk_len": report.avg_chunk_len,
        "chunks_too_short": report.chunks_too_short,
        "chunks_too_long": report.chunks_too_long,
        "entities": report.entities,
    }


def search_knowledge(ports: Ports, query: str, k: int = 5) -> list[dict]:
    """UI-6 knowledge-base search preview, the same dense query path the retrieval service uses,
    so what the administrator previews is what the pipeline will retrieve."""
    vector = ports.embedder.embed([query])[0]
    return [
        {
            "chunk_id": metadata.get("chunk_id"),
            "score": score,
            "text": text,
            "metadata": metadata,
        }
        for text, score, metadata in ports.vector_index.query(vector, k=k)
    ]


def health() -> dict:
    return {"status": "ok"}


def list_dlq(engine: Engine) -> list[dict]:
    with session_scope(engine) as session:
        rows = DlqEntryRepo(session).list_unreplayed()
        return [
            {
                "id": r.id,
                "ticket_id": r.ticket_id,
                "original_topic": r.original_topic,
                "original_group": r.original_group,
                "error": r.error,
                "attempts": r.attempts,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


def replay_dlq_entry(engine: Engine, broker: EventBrokerPort, entry_id: str) -> dict:
    with session_scope(engine) as session:
        entry = DlqEntryRepo(session).get(entry_id)
        if entry is None:
            raise ValueError(f"dlq entry {entry_id} not found")
        original_envelope_data = entry.body.get("original_envelope")
        original_topic = entry.original_topic
        original_key = entry.body.get("original_key", entry.ticket_id)
        DlqEntryRepo(session).mark_replayed(entry_id)

    if not original_envelope_data or not original_topic:
        raise ValueError(f"dlq entry {entry_id} is missing the original envelope; cannot replay")

    broker.produce(original_topic, original_key, EventEnvelope.model_validate(original_envelope_data))
    return {"replayed": True, "topic": original_topic}
