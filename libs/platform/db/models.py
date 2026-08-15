"""SQLAlchemy 2 declarative ORM, SAD §9.2 minimum table set for v1."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _ulid() -> str:
    from ulid import ULID

    return str(ULID())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # agent | lead | admin
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    segment: Mapped[str] = mapped_column(String, default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Ticket(Base):
    __tablename__ = "ticket"
    __table_args__ = (
        CheckConstraint(
            "priority_score IS NULL OR priority_score BETWEEN 0 AND 100", name="ck_ticket_priority_score"
        ),
        Index(
            "ux_ticket_org_idempotency_key",
            "org_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="RECEIVED")
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority_band: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    attachments: Mapped[list["Attachment"]] = relationship(back_populates="ticket")


class Attachment(Base):
    __tablename__ = "attachment"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    modality: Mapped[str] = mapped_column(String, nullable=False)  # audio | image
    object_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    ticket: Mapped[Ticket] = relationship(back_populates="attachments")


class AudioTranscriptRow(Base):
    __tablename__ = "audio_transcript"
    __table_args__ = (UniqueConstraint("attachment_id", "model_version", name="ux_audio_transcript_att_model"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    attachment_id: Mapped[str] = mapped_column(ForeignKey("attachment.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    acoustic_sentiment: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class VisualSummaryRow(Base):
    __tablename__ = "visual_summary"
    __table_args__ = (UniqueConstraint("attachment_id", "model_version", name="ux_visual_summary_att_model"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    attachment_id: Mapped[str] = mapped_column(ForeignKey("attachment.id"), nullable=False)
    prompt_template: Mapped[str] = mapped_column(String, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UnifiedPayloadRow(Base):
    __tablename__ = "unified_payload"
    __table_args__ = (UniqueConstraint("ticket_id", "revision", name="ux_unified_payload_ticket_revision"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_version: Mapped[str] = mapped_column(String, nullable=False, default="1.0.0")
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    fused_text: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TriageResultRow(Base):
    __tablename__ = "triage_result"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    department: Mapped[str] = mapped_column(String, nullable=False)
    department_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    sentiment: Mapped[str] = mapped_column(String, nullable=False)
    signals: Mapped[list] = mapped_column(JSON, default=list)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DiagnosisRow(Base):
    __tablename__ = "diagnosis"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    intent: Mapped[str] = mapped_column(String, nullable=False)
    fault: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    needs_human_diagnosis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CitationRow(Base):
    __tablename__ = "citation"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("diagnosis.id"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    relevance: Mapped[float] = mapped_column(Float, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DraftResponseRow(Base):
    __tablename__ = "draft_response"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    ai_text: Mapped[str] = mapped_column(Text, nullable=False)
    current_text: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ActionRecommendationRow(Base):
    __tablename__ = "action_recommendation"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    action_id: Mapped[str] = mapped_column(String, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    requires_supervisor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PROPOSED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionExecutionRow(Base):
    __tablename__ = "action_execution"
    __table_args__ = (
        UniqueConstraint("ticket_id", "action_id", "parameters_hash", name="ux_action_execution_idem"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    action_id: Mapped[str] = mapped_column(String, nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentDecisionRow(Base):
    __tablename__ = "agent_decision"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reason_code: Mapped[str | None] = mapped_column(String, nullable=True)
    before: Mapped[str | None] = mapped_column(Text, nullable=True)
    after: Mapped[str | None] = mapped_column(Text, nullable=True)


class TrainingExampleRow(Base):
    """One human-confirmed label, harvested from an agent decision.

    This is the substrate of the continuous-learning loop. Every row records what the model
    predicted, what the human decided it should have been, and which artefact version produced
    the prediction, so a retrain can be traced back to the exact interactions that justified it.

    Rows are append-only and immutable. `consumed_by_run` is stamped when a training run reads
    the row, so a given example is never silently counted twice across retrains, and a run can
    be reproduced by selecting exactly the rows it consumed.
    """

    __tablename__ = "training_example"
    __table_args__ = (
        UniqueConstraint("decision_id", "task", name="ux_training_example_decision_task"),
        Index("ix_training_example_unconsumed", "task", "consumed_by_run"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    decision_id: Mapped[str] = mapped_column(ForeignKey("agent_decision.id"), nullable=False)

    # Which model this example trains: department | priority | draft | fault
    task: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    predicted: Mapped[str | None] = mapped_column(String, nullable=True)
    corrected: Mapped[str] = mapped_column(String, nullable=False)
    model_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)

    # False when the human agreed with the model. Agreements are still recorded: a retrain that
    # only ever sees corrections learns a badly skewed view of the input distribution.
    is_correction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    actor_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    consumed_by_run: Mapped[str | None] = mapped_column(String, nullable=True)


class RetrainRunRow(Base):
    """One execution of the retraining pipeline, successful or not.

    Kept in the operational database rather than only in MLflow so the admin console can show
    retraining history without depending on the tracking server being reachable.
    """

    __tablename__ = "retrain_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    task: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="RUNNING")
    trigger: Mapped[str] = mapped_column(String, nullable=False)  # manual | scheduled | threshold

    examples_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    examples_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    baseline_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_name: Mapped[str] = mapped_column(String, nullable=False, default="macro_f1")
    promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    mlflow_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    dvc_data_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeliveryRow(Base):
    __tablename__ = "delivery"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    draft_response_id: Mapped[str] = mapped_column(ForeignKey("draft_response.id"), nullable=False)
    approval_id: Mapped[str] = mapped_column(ForeignKey("agent_decision.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    channel: Mapped[str] = mapped_column(String, nullable=False)
    to_address: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditRecordRow(Base):
    __tablename__ = "audit_record"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("ticket.id"), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OutboxRow(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QueueProjectionRow(Base):
    __tablename__ = "queue_projection"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False, unique=True)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_band: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # Denormalised UI-2 columns: the queue view renders entirely from this row, so nothing in the
    # read path joins the analysis tables (SAD §5.2.2 read model, ADR-009).
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    department_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    fault: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnosis_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    modalities: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    ticket_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeDocumentRow(Base):
    __tablename__ = "knowledge_document"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    doc_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunk"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_document.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionRegistryEntryRow(Base):
    __tablename__ = "action_registry_entry"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    action_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    department: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mapped_faults: Mapped[list] = mapped_column(JSON, default=list)
    requires_supervisor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_fields: Mapped[list] = mapped_column(JSON, default=list)
    impact_limits: Mapped[dict] = mapped_column(JSON, default=dict)


class ConfigVersionRow(Base):
    __tablename__ = "config_version"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    changed_by: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AggregationStateRow(Base):
    __tablename__ = "aggregation_state"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False, unique=True)
    expected_set: Mapped[list] = mapped_column(JSON, default=list)
    window_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="OPEN")
    original_text: Mapped[str] = mapped_column(Text, default="")
    text_flags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AggregationReceivedItemRow(Base):
    """Append-only table for per-item completion markers. Concurrent broker worker threads can
    process tickets.text.done / tickets.audio.done / tickets.image.done for the SAME ticket at
    the same time; a read-modify-write on a JSON list column on AggregationStateRow would lose
    updates under that concurrency. Insert-only with a uniqueness constraint is race-free."""

    __tablename__ = "aggregation_received_item"
    __table_args__ = (UniqueConstraint("ticket_id", "item", name="ux_aggregation_received_item"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    item: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DlqEntryRow(Base):
    """Durable capture of events produced to `tickets.dlq` (in-process broker events with no
    persistence of their own would otherwise vanish) so admin_api can list and replay them."""

    __tablename__ = "dlq_entry"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(String, nullable=False)
    original_topic: Mapped[str] = mapped_column(String, nullable=False)
    original_group: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TicketStateTransitionRow(Base):
    __tablename__ = "ticket_state_transition"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_ulid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), nullable=False)
    from_state: Mapped[str] = mapped_column(String, nullable=False)
    to_state: Mapped[str] = mapped_column(String, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
