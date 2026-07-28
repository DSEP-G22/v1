"""Transactional outbox. `enqueue` writes in the same transaction as the state change;
`drain` is the only place that calls `broker.produce()` for outbox-originated events."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from libs.domain.contracts.events import EventEnvelope
from libs.domain.ports.event_broker import EventBrokerPort
from libs.platform.db.models import OutboxRow


def enqueue(session: Session, topic: str, key: str, envelope: EventEnvelope) -> None:
    session.add(
        OutboxRow(topic=topic, key=key, payload=envelope.model_dump(mode="json"))
    )


def drain(broker: EventBrokerPort, engine: Engine, batch_size: int = 100) -> int:
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    published = 0
    with factory() as session:
        rows = (
            session.execute(
                select(OutboxRow).where(OutboxRow.published_at.is_(None)).limit(batch_size)
            )
            .scalars()
            .all()
        )
        for row in rows:
            envelope = EventEnvelope.model_validate(row.payload)
            broker.produce(row.topic, row.key, envelope)
            row.published_at = datetime.now(timezone.utc)
            published += 1
        session.commit()
    return published
