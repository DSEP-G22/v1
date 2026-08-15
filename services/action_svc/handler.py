"""Re-validates an action recommendation against the current action registry (never trusts the
recommendation blindly, the registry may have changed since response_svc proposed it), then
executes it idempotently keyed by (ticket_id, action_id, sha256(params)). Only this package may
import ActionAdapterPort (SAD Figure 14)."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.engine import Engine

from libs.domain.enums import ExecutionStatus
from libs.domain.policy.action_selection import ActionRegistryEntry
from libs.domain.ports.action_adapter import ActionAdapterPort
from libs.domain.contracts.analysis import RecommendationStatus
from libs.platform.db.repositories import ActionExecutionRepo, ActionRecommendationRepo, ActionRegistryEntryRepo
from libs.platform.db.session import session_scope


class ActionRefused(ValueError):
    pass


def _hash_params(parameters: dict) -> str:
    return hashlib.sha256(json.dumps(parameters, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def execute_recommendation(
    action_adapter: ActionAdapterPort, engine: Engine, *, ticket_id: str, recommendation_id: str
) -> dict:
    with session_scope(engine) as session:
        recommendation = ActionRecommendationRepo(session).get(recommendation_id)
        if recommendation is None or recommendation.ticket_id != ticket_id:
            raise ActionRefused(f"no action_recommendation {recommendation_id} for ticket {ticket_id}")

        registry_row = next(
            (r for r in ActionRegistryEntryRepo(session).list_all() if r.action_id == recommendation.action_id),
            None,
        )
        if registry_row is None:
            raise ActionRefused(f"action_id {recommendation.action_id} is not in the registry")

        entry = ActionRegistryEntry(
            action_id=registry_row.action_id,
            mapped_faults=registry_row.mapped_faults,
            requires_supervisor=registry_row.requires_supervisor,
            enabled=registry_row.enabled,
            requires_fields=registry_row.requires_fields,
            impact_limits=registry_row.impact_limits,
        )
        if not entry.permits(recommendation.parameters):
            raise ActionRefused(f"registry no longer permits action {entry.action_id} with the given parameters")

        parameters_hash = _hash_params(recommendation.parameters)
        idempotency_key = f"{ticket_id}:{recommendation.action_id}:{parameters_hash}"

        execution = ActionExecutionRepo(session).create_if_absent(
            ticket_id=ticket_id,
            action_id=recommendation.action_id,
            parameters_hash=parameters_hash,
            status=ExecutionStatus.PENDING.value,
            idempotency_key=idempotency_key,
        )

        if execution.status == ExecutionStatus.SUCCEEDED.value:
            return {"execution_id": execution.id, "status": execution.status, "idempotent_replay": True}

        action_id = recommendation.action_id
        parameters = dict(recommendation.parameters)
        execution_id = execution.id

    result = action_adapter.execute(action_id, parameters, idempotency_key)

    with session_scope(engine) as session:
        ActionExecutionRepo(session).set_status(execution_id, result.status.value, result.external_ref)
        if result.status == ExecutionStatus.SUCCEEDED:
            ActionRecommendationRepo(session).set_status(recommendation_id, RecommendationStatus.EXECUTED)

    return {"execution_id": execution_id, "status": result.status.value, "idempotent_replay": False}
