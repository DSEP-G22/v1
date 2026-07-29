"""Simulated ActionAdapterPort and MailGatewayPort implementations for v1 (SAD: "simulated
adapters in v1" for ActionAdapterPort; MailGatewayPort has no real SMTP/API integration yet)."""

from __future__ import annotations

import logging
from typing import Any

from libs.domain.enums import ExecutionStatus
from libs.domain.ports.action_adapter import ExecutionResult

logger = logging.getLogger(__name__)


class SimulatedActionAdapter:
    def execute(self, action_id: str, params: dict[str, Any], idempotency_key: str) -> ExecutionResult:
        logger.info(
            "simulated action execute",
            extra={"action_id": action_id, "idempotency_key": idempotency_key},
        )
        return ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            external_ref=f"sim-{idempotency_key}",
            detail=f"simulated execution of {action_id} with params={params}",
        )


class ConsoleMailGateway:
    """Logs the outbound message instead of sending it. Swap for a real SMTP/API-backed
    adapter behind the same MailGatewayPort without touching delivery_gateway."""

    def send(self, to: str, subject: str, body: str) -> str:
        message_id = f"console-{abs(hash((to, subject, body)))}"
        logger.info("simulated mail send", extra={"to": to, "subject": subject, "message_id": message_id})
        return message_id
