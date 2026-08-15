"""Harvests training examples from human decisions (the continuous-learning loop).

Every time an agent approves, edits, rejects or reassigns, they are implicitly labelling the
model's output. This module converts those decisions into rows in `training_example`, which is
the only input the retraining pipeline reads.

Design decisions worth stating, because they determine whether the loop improves the model or
quietly poisons it:

*   **Agreements are recorded, not just corrections.** An approval with no edit is evidence the
    prediction was right. A dataset built only from corrections would teach the model that its
    confident, correct predictions are the exception.

*   **A reassignment is a department label, an escalation is not.** Reassigning to
    `network_operations` states plainly what the department should have been. Escalating says
    the priority was too low but says nothing about which department is correct, so it produces
    a priority example only.

*   **Draft edits are captured but not used for supervised training here.** The edit distance
    feeds evaluation, and the pairs are retained for a future preference-tuning run. Treating a
    lightly reworded reply as a "correct answer" would train the model toward one agent's prose
    style rather than toward correctness.

*   **The ticket's own text is the training input**, taken from the unified payload, so the
    example matches what the classifier actually sees at inference time.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

from libs.domain.enums import DecisionType
from libs.observability.logging import get_logger
from libs.platform.db.repositories import (
    DiagnosisRepo,
    TicketRepo,
    TrainingExampleRepo,
    TriageResultRepo,
    UnifiedPayloadRepo,
)
from libs.platform.db.session import session_scope

logger = get_logger(__name__)

TASK_DEPARTMENT = "department"
TASK_PRIORITY = "priority"
TASK_DRAFT = "draft"
TASK_FAULT = "fault"


def harvest_decision(engine: Engine, decision_id: str) -> list[str]:
    """Convert one agent decision into training examples. Returns the example ids created.

    Idempotent: the unique constraint on (decision_id, task) means replaying a decision, which
    at-least-once delivery makes likely, cannot duplicate a label.
    """
    created: list[str] = []

    with session_scope(engine) as session:
        from libs.platform.db.models import AgentDecisionRow

        decision = session.get(AgentDecisionRow, decision_id)
        if decision is None:
            return []

        ticket_id = decision.ticket_id
        payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
        if payload is None or not payload.fused_text.strip():
            # No input text means nothing trainable, whatever the human decided.
            return []

        text = payload.fused_text
        ticket = TicketRepo(session).get(ticket_id)
        triage = TriageResultRepo(session).get_latest(ticket_id)
        diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
        repo = TrainingExampleRepo(session)

        def record(task: str, corrected: str, predicted: str | None,
                   confidence: float | None, is_correction: bool) -> None:
            if not corrected:
                return
            row = repo.add(
                ticket_id=ticket_id,
                decision_id=decision_id,
                task=task,
                text=text,
                predicted=predicted,
                corrected=corrected,
                model_confidence=confidence,
                model_version=getattr(triage, "model_version", None),
                is_correction=is_correction,
                actor_id=decision.actor_id,
            )
            if row is not None:
                created.append(row.id)

        decision_type = decision.type

        if decision_type == DecisionType.REASSIGN.value:
            # `before` and `after` hold the departments, written by workspace_api.reassign_ticket.
            record(
                TASK_DEPARTMENT,
                corrected=decision.after or "",
                predicted=decision.before,
                confidence=triage.department_confidence if triage else None,
                is_correction=True,
            )

        elif decision_type == DecisionType.ESCALATE.value:
            # Says the band was too low. Carries no information about the department.
            record(
                TASK_PRIORITY,
                corrected="critical",
                predicted=decision.before,
                confidence=None,
                is_correction=True,
            )

        elif decision_type == DecisionType.APPROVE_SEND.value:
            # The human accepted the routing and the diagnosis, so both are confirmed labels.
            if triage is not None:
                record(
                    TASK_DEPARTMENT,
                    corrected=triage.department,
                    predicted=triage.department,
                    confidence=triage.department_confidence,
                    is_correction=False,
                )
                record(
                    TASK_PRIORITY,
                    corrected=triage.band,
                    predicted=triage.band,
                    confidence=None,
                    is_correction=False,
                )
            if diagnosis is not None and diagnosis.fault:
                record(
                    TASK_FAULT,
                    corrected=diagnosis.fault,
                    predicted=diagnosis.fault,
                    confidence=diagnosis.confidence,
                    is_correction=False,
                )
            # The edited reply is retained for preference tuning, never as a supervised target.
            if decision.before and decision.after and decision.before != decision.after:
                record(
                    TASK_DRAFT,
                    corrected=decision.after,
                    predicted=decision.before,
                    confidence=None,
                    is_correction=True,
                )

        elif decision_type == DecisionType.REJECT.value:
            # A rejection says the draft was wrong but not what the right answer was. The only
            # reliable signal is the reason code, and only when it names the failure mode.
            if decision.reason_code == "wrong_department" and ticket is not None:
                logger.info(
                    "rejection flagged wrong_department but no target given; no label harvested",
                    extra={"ticket_id": ticket_id, "stage": "feedback"},
                )

        if created:
            logger.info(
                f"harvested {len(created)} training example(s) from {decision_type}",
                extra={"ticket_id": ticket_id, "stage": "feedback"},
            )

    return created


def pending_counts(engine: Engine) -> dict[str, int]:
    """Unconsumed example count per task, used by the admin console and the retrain trigger."""
    with session_scope(engine) as session:
        repo = TrainingExampleRepo(session)
        return {
            task: repo.count_unconsumed(task)
            for task in (TASK_DEPARTMENT, TASK_PRIORITY, TASK_FAULT, TASK_DRAFT)
        }
