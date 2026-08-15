"""One repository class per aggregate. SAD §5.2.2 single-writer rule: each table is written by
exactly one service package. `TABLE_OWNERS` is the source of truth for that rule and is
enforced by `tests/architecture/test_single_writer.py`, which greps each `services/*` package
for repository write-method calls against tables it does not own.

Table owners:
  ticket, attachment                        -> intake_api (create); triage_svc/response_svc/
                                                workspace_api update state/department narrowly
  aggregation_state                         -> routing_svc (create), aggregator_svc (update)
  audio_transcript                          -> audio_svc
  visual_summary                            -> image_svc
  unified_payload                           -> aggregator_svc
  triage_result                             -> triage_svc
  diagnosis, citation                       -> orchestrator_svc
  draft_response, action_recommendation     -> response_svc (create); workspace_api (edit);
                                                action_svc (status update on recommendation)
  queue_projection                          -> projector_svc
  agent_decision                            -> workspace_api
  delivery                                  -> delivery_gateway
  action_execution                          -> action_svc
  knowledge_document, knowledge_chunk       -> knowledge_ingest
  action_registry_entry, config_version,
    app_user, organization, customer        -> admin_api
  audit_record                              -> any service, append-only
  ticket_state_transition                   -> written alongside the state-owning writer above
  outbox                                    -> any service, append-only via libs.platform.db.outbox
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from libs.platform.db.models import (
    RetrainRunRow,
    TrainingExampleRow,
    ActionExecutionRow,
    ActionRecommendationRow,
    ActionRegistryEntryRow,
    AgentDecisionRow,
    AggregationReceivedItemRow,
    AggregationStateRow,
    AppUser,
    Attachment,
    AudioTranscriptRow,
    AuditRecordRow,
    CitationRow,
    ConfigVersionRow,
    Customer,
    DeliveryRow,
    DiagnosisRow,
    DlqEntryRow,
    DraftResponseRow,
    KnowledgeChunkRow,
    KnowledgeDocumentRow,
    Organization,
    QueueProjectionRow,
    Ticket,
    TicketStateTransitionRow,
    TriageResultRow,
    UnifiedPayloadRow,
    VisualSummaryRow,
)


class TicketRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> Ticket:
        row = Ticket(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, ticket_id: str) -> Ticket | None:
        return self._session.get(Ticket, ticket_id)

    def update_state(self, ticket_id: str, from_state: str, to_state: str) -> None:
        ticket = self._session.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError(f"ticket {ticket_id} not found")
        ticket.state = to_state
        self._session.add(
            TicketStateTransitionRow(ticket_id=ticket_id, from_state=from_state, to_state=to_state)
        )

    def update_triage_summary(self, ticket_id: str, department: str, priority_score: int, priority_band: str) -> None:
        ticket = self._session.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError(f"ticket {ticket_id} not found")
        ticket.department = department
        ticket.priority_score = priority_score
        ticket.priority_band = priority_band


class AttachmentRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> Attachment:
        row = Attachment(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, attachment_id: str) -> Attachment | None:
        return self._session.get(Attachment, attachment_id)

    def list_for_ticket(self, ticket_id: str) -> list[Attachment]:
        return list(self._session.execute(select(Attachment).where(Attachment.ticket_id == ticket_id)).scalars())

    def set_status(self, attachment_id: str, status: str) -> None:
        att = self._session.get(Attachment, attachment_id)
        if att is not None:
            att.status = status


class AggregationStateRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> AggregationStateRow:
        row = AggregationStateRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get_by_ticket(self, ticket_id: str) -> AggregationStateRow | None:
        return self._session.execute(
            select(AggregationStateRow).where(AggregationStateRow.ticket_id == ticket_id)
        ).scalar_one_or_none()

    def set_text(self, ticket_id: str, original_text: str, flags: list[str]) -> None:
        state = self.get_by_ticket(ticket_id)
        if state is not None:
            state.original_text = original_text
            state.text_flags = flags

    def set_status(self, ticket_id: str, status: str) -> None:
        state = self.get_by_ticket(ticket_id)
        if state is not None:
            state.status = status

    def list_expired(self, now) -> list[AggregationStateRow]:
        return list(
            self._session.execute(
                select(AggregationStateRow).where(
                    AggregationStateRow.status == "OPEN", AggregationStateRow.window_expires_at <= now
                )
            ).scalars()
        )


class AggregationReceivedItemRepo:
    """Race-free completion tracking, see AggregationReceivedItemRow docstring."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def mark(self, ticket_id: str, item: str) -> None:
        stmt = sqlite_insert(AggregationReceivedItemRow).values(ticket_id=ticket_id, item=item)
        stmt = stmt.on_conflict_do_nothing(index_elements=["ticket_id", "item"])
        self._session.execute(stmt)

    def list_for(self, ticket_id: str) -> list[str]:
        return list(
            self._session.execute(
                select(AggregationReceivedItemRow.item).where(AggregationReceivedItemRow.ticket_id == ticket_id)
            ).scalars()
        )


class AudioTranscriptRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, **kwargs) -> None:
        stmt = sqlite_insert(AudioTranscriptRow).values(**kwargs)
        stmt = stmt.on_conflict_do_nothing(index_elements=["attachment_id", "model_version"])
        self._session.execute(stmt)

    def list_for_attachment(self, attachment_id: str) -> list[AudioTranscriptRow]:
        return list(
            self._session.execute(
                select(AudioTranscriptRow).where(AudioTranscriptRow.attachment_id == attachment_id)
            ).scalars()
        )


class VisualSummaryRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, **kwargs) -> None:
        stmt = sqlite_insert(VisualSummaryRow).values(**kwargs)
        stmt = stmt.on_conflict_do_nothing(index_elements=["attachment_id", "model_version"])
        self._session.execute(stmt)

    def list_for_attachment(self, attachment_id: str) -> list[VisualSummaryRow]:
        return list(
            self._session.execute(
                select(VisualSummaryRow).where(VisualSummaryRow.attachment_id == attachment_id)
            ).scalars()
        )


class UnifiedPayloadRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> UnifiedPayloadRow:
        stmt = sqlite_insert(UnifiedPayloadRow).values(**kwargs)
        stmt = stmt.on_conflict_do_nothing(index_elements=["ticket_id", "revision"])
        self._session.execute(stmt)
        self._session.flush()
        return self.get_latest(kwargs["ticket_id"])

    def get_latest(self, ticket_id: str) -> UnifiedPayloadRow | None:
        return self._session.execute(
            select(UnifiedPayloadRow)
            .where(UnifiedPayloadRow.ticket_id == ticket_id)
            .order_by(UnifiedPayloadRow.revision.desc())
            .limit(1)
        ).scalar_one_or_none()


class TriageResultRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> TriageResultRow:
        row = TriageResultRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get_latest(self, ticket_id: str) -> TriageResultRow | None:
        return self._session.execute(
            select(TriageResultRow)
            .where(TriageResultRow.ticket_id == ticket_id)
            .order_by(TriageResultRow.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()


class DiagnosisRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, citations: list[dict] | None = None, **kwargs) -> DiagnosisRow:
        row = DiagnosisRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        for citation in citations or []:
            self._session.add(CitationRow(diagnosis_id=row.id, **citation))
        return row

    def get_latest(self, ticket_id: str) -> DiagnosisRow | None:
        return self._session.execute(
            select(DiagnosisRow)
            .where(DiagnosisRow.ticket_id == ticket_id)
            .order_by(DiagnosisRow.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def citations_for(self, diagnosis_id: str) -> list[CitationRow]:
        return list(
            self._session.execute(select(CitationRow).where(CitationRow.diagnosis_id == diagnosis_id)).scalars()
        )


class DraftResponseRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> DraftResponseRow:
        row = DraftResponseRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get_latest(self, ticket_id: str) -> DraftResponseRow | None:
        return self._session.execute(
            select(DraftResponseRow)
            .where(DraftResponseRow.ticket_id == ticket_id)
            .order_by(DraftResponseRow.revision.desc())
            .limit(1)
        ).scalar_one_or_none()

    def update_current_text(self, draft_id: str, current_text: str) -> None:
        row = self._session.get(DraftResponseRow, draft_id)
        if row is not None:
            row.current_text = current_text
            row.revision += 1


class ActionRecommendationRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> ActionRecommendationRow:
        row = ActionRecommendationRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, rec_id: str) -> ActionRecommendationRow | None:
        return self._session.get(ActionRecommendationRow, rec_id)

    def list_for_ticket(self, ticket_id: str) -> list[ActionRecommendationRow]:
        return list(
            self._session.execute(
                select(ActionRecommendationRow)
                .where(ActionRecommendationRow.ticket_id == ticket_id)
                .order_by(ActionRecommendationRow.created_at)
            ).scalars()
        )

    def set_status(self, rec_id: str, status: str) -> None:
        row = self._session.get(ActionRecommendationRow, rec_id)
        if row is not None:
            row.status = status


class ActionExecutionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_if_absent(self, **kwargs) -> ActionExecutionRow | None:
        stmt = sqlite_insert(ActionExecutionRow).values(**kwargs)
        stmt = stmt.on_conflict_do_nothing(index_elements=["ticket_id", "action_id", "parameters_hash"])
        self._session.execute(stmt)
        self._session.flush()
        return self._session.execute(
            select(ActionExecutionRow).where(
                ActionExecutionRow.ticket_id == kwargs["ticket_id"],
                ActionExecutionRow.action_id == kwargs["action_id"],
                ActionExecutionRow.parameters_hash == kwargs["parameters_hash"],
            )
        ).scalar_one_or_none()

    def set_status(self, execution_id: str, status: str, external_ref: str | None = None) -> None:
        row = self._session.get(ActionExecutionRow, execution_id)
        if row is not None:
            row.status = status
            if external_ref is not None:
                row.external_ref = external_ref


class AgentDecisionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> AgentDecisionRow:
        row = AgentDecisionRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def list_for_ticket(self, ticket_id: str) -> list[AgentDecisionRow]:
        return list(
            self._session.execute(
                select(AgentDecisionRow)
                .where(AgentDecisionRow.ticket_id == ticket_id)
                .order_by(AgentDecisionRow.at)
            ).scalars()
        )

    def list_all(self) -> list[AgentDecisionRow]:
        """Supervisor dashboard (UI-4): AI acceptance / edit / rejection rates are computed from
        the decision log, which is the only place they are recorded."""
        return list(self._session.execute(select(AgentDecisionRow).order_by(AgentDecisionRow.at)).scalars())


class DeliveryRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> DeliveryRow:
        if not kwargs.get("approval_id"):
            raise ValueError("delivery.approval_id is required (SAD: no send without an agent_decision)")
        row = DeliveryRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row


class AuditRecordRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> AuditRecordRow:
        row = AuditRecordRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row


class QueueProjectionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, ticket_id: str, **fields) -> None:
        row = self._session.execute(
            select(QueueProjectionRow).where(QueueProjectionRow.ticket_id == ticket_id)
        ).scalar_one_or_none()
        if row is None:
            self._session.add(QueueProjectionRow(ticket_id=ticket_id, **fields))
        else:
            for key, value in fields.items():
                setattr(row, key, value)

    def list_queue(self, department: str | None = None) -> list[QueueProjectionRow]:
        stmt = select(QueueProjectionRow)
        if department is not None:
            stmt = stmt.where(QueueProjectionRow.department == department)
        return list(self._session.execute(stmt).scalars())

    def get(self, ticket_id: str) -> QueueProjectionRow | None:
        return self._session.execute(
            select(QueueProjectionRow).where(QueueProjectionRow.ticket_id == ticket_id)
        ).scalar_one_or_none()

    def set_lock(self, ticket_id: str, locked_by: str | None) -> None:
        row = self.get(ticket_id)
        if row is not None:
            row.locked_by = locked_by


class KnowledgeDocumentRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> KnowledgeDocumentRow:
        row = KnowledgeDocumentRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def list_all(self) -> list[KnowledgeDocumentRow]:
        return list(self._session.execute(select(KnowledgeDocumentRow)).scalars())


class KnowledgeChunkRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> KnowledgeChunkRow:
        row = KnowledgeChunkRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def list_for_document(self, document_id: str) -> list[KnowledgeChunkRow]:
        return list(
            self._session.execute(
                select(KnowledgeChunkRow).where(KnowledgeChunkRow.document_id == document_id)
            ).scalars()
        )

    def get(self, chunk_id: str) -> KnowledgeChunkRow | None:
        return self._session.get(KnowledgeChunkRow, chunk_id)


class ActionRegistryEntryRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, action_id: str, **fields) -> ActionRegistryEntryRow:
        row = self._session.execute(
            select(ActionRegistryEntryRow).where(ActionRegistryEntryRow.action_id == action_id)
        ).scalar_one_or_none()
        if row is None:
            row = ActionRegistryEntryRow(action_id=action_id, **fields)
            self._session.add(row)
        else:
            for key, value in fields.items():
                setattr(row, key, value)
        self._session.flush()
        return row

    def list_all(self) -> list[ActionRegistryEntryRow]:
        return list(self._session.execute(select(ActionRegistryEntryRow)).scalars())


class AppUserRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> AppUser:
        row = AppUser(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get_by_username(self, username: str) -> AppUser | None:
        return self._session.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none()

    def list_all(self) -> list[AppUser]:
        return list(self._session.execute(select(AppUser).order_by(AppUser.username)).scalars())


class ConfigVersionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> ConfigVersionRow:
        row = ConfigVersionRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row


class OrganizationRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> Organization:
        row = Organization(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def first(self) -> Organization | None:
        return self._session.execute(select(Organization).limit(1)).scalar_one_or_none()


class CustomerRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> Customer:
        row = Customer(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, customer_id: str) -> Customer | None:
        return self._session.get(Customer, customer_id)


class DlqEntryRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> DlqEntryRow:
        row = DlqEntryRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def list_unreplayed(self) -> list[DlqEntryRow]:
        return list(
            self._session.execute(select(DlqEntryRow).where(DlqEntryRow.replayed_at.is_(None))).scalars()
        )

    def get(self, entry_id: str) -> DlqEntryRow | None:
        return self._session.get(DlqEntryRow, entry_id)

    def mark_replayed(self, entry_id: str) -> None:
        row = self.get(entry_id)
        if row is not None:
            from datetime import datetime, timezone

            row.replayed_at = datetime.now(timezone.utc)


class TrainingExampleRepo:
    """Append-only store of human-confirmed labels (the continuous-learning substrate)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, **kwargs) -> TrainingExampleRow | None:
        """Idempotent on (decision_id, task): replaying a decision event cannot duplicate a label."""
        stmt = sqlite_insert(TrainingExampleRow).values(**kwargs)
        stmt = stmt.on_conflict_do_nothing(index_elements=["decision_id", "task"])
        self._session.execute(stmt)
        self._session.flush()
        return self._session.execute(
            select(TrainingExampleRow).where(
                TrainingExampleRow.decision_id == kwargs["decision_id"],
                TrainingExampleRow.task == kwargs["task"],
            )
        ).scalar_one_or_none()

    def list_for_task(self, task: str, only_unconsumed: bool = False) -> list[TrainingExampleRow]:
        stmt = select(TrainingExampleRow).where(TrainingExampleRow.task == task)
        if only_unconsumed:
            stmt = stmt.where(TrainingExampleRow.consumed_by_run.is_(None))
        return list(self._session.execute(stmt.order_by(TrainingExampleRow.created_at)).scalars())

    def count_unconsumed(self, task: str) -> int:
        return len(self.list_for_task(task, only_unconsumed=True))

    def mark_consumed(self, ids: list[str], run_id: str) -> None:
        for example_id in ids:
            row = self._session.get(TrainingExampleRow, example_id)
            if row is not None:
                row.consumed_by_run = run_id


class RetrainRunRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> RetrainRunRow:
        row = RetrainRunRow(**kwargs)
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, run_id: str) -> RetrainRunRow | None:
        return self._session.get(RetrainRunRow, run_id)

    def finish(self, run_id: str, **fields) -> None:
        row = self._session.get(RetrainRunRow, run_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        row.finished_at = datetime.now(timezone.utc)

    def list_recent(self, limit: int = 20) -> list[RetrainRunRow]:
        return list(
            self._session.execute(
                select(RetrainRunRow).order_by(RetrainRunRow.started_at.desc()).limit(limit)
            ).scalars()
        )
