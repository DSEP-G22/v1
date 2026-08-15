"""REQ-BR-1, REQ-SAFE-1, the only egress path. Refuses to send without a persisted
`agent_decision.id`; only this package may import MailGatewayPort (SAD Figure 14)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.engine import Engine

from libs.domain.enums import DeliveryStatus
from libs.domain.ports.mail_gateway import MailGatewayPort
from libs.platform.db.repositories import DeliveryRepo
from libs.platform.db.session import session_scope


class DeliveryRefused(ValueError):
    pass


def send(
    mail_gateway: MailGatewayPort,
    engine: Engine,
    *,
    ticket_id: str,
    draft_response_id: str,
    approval_id: str | None,
    channel: str,
    to_address: str,
    subject: str,
    body: str,
) -> dict:
    if not approval_id:
        raise DeliveryRefused(
            f"refusing to send ticket_id={ticket_id}: no agent_decision approval_id on file"
        )

    try:
        external_ref = mail_gateway.send(to_address, subject, body)
        status = DeliveryStatus.SENT.value
    except Exception:
        external_ref = None
        status = DeliveryStatus.FAILED.value

    with session_scope(engine) as session:
        delivery = DeliveryRepo(session).create(
            ticket_id=ticket_id,
            draft_response_id=draft_response_id,
            approval_id=approval_id,
            status=status,
            channel=channel,
            to_address=to_address,
            sent_at=datetime.now(timezone.utc) if status == DeliveryStatus.SENT.value else None,
        )
        return {"delivery_id": delivery.id, "status": status, "external_ref": external_ref}
