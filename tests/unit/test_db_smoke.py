from libs.domain.contracts.events import EventEnvelope, Topics
from libs.platform.broker.inprocess import InProcessBroker
from libs.platform.db import outbox
from libs.platform.db.repositories import CustomerRepo, OrganizationRepo, TicketRepo
from libs.platform.db.session import build_engine, init_db, session_scope


def test_create_ticket_and_drain_outbox(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/t.db")
    init_db(engine)

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Acme Telecom")
        customer = CustomerRepo(session).create(org_id=org.id, name="Jane Doe")
        ticket = TicketRepo(session).create(
            org_id=org.id, customer_id=customer.id, channel="web_portal", state="RECEIVED"
        )
        outbox.enqueue(
            session,
            Topics.TICKETS_RAW,
            ticket.id,
            EventEnvelope(event_id="e1", ticket_id=ticket.id, stage="intake", body={}),
        )
        ticket_id = ticket.id

    with session_scope(engine) as session:
        fetched = TicketRepo(session).get(ticket_id)
        assert fetched is not None
        assert fetched.state == "RECEIVED"

    broker = InProcessBroker()
    received = []
    broker.subscribe(Topics.TICKETS_RAW, "test-group", lambda env: received.append(env))
    broker.start()
    try:
        n = outbox.drain(broker, engine)
        assert n == 1
        import time

        for _ in range(20):
            if received:
                break
            time.sleep(0.05)
        assert len(received) == 1
        assert received[0].ticket_id == ticket_id
    finally:
        broker.stop()


def test_idempotency_key_uniqueness_enforced(tmp_path):
    import pytest
    from sqlalchemy.exc import IntegrityError

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/t2.db")
    init_db(engine)

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Acme Telecom")
        customer = CustomerRepo(session).create(org_id=org.id, name="Jane Doe")
        TicketRepo(session).create(
            org_id=org.id, customer_id=customer.id, channel="web_portal", idempotency_key="dup-1"
        )

    with pytest.raises(IntegrityError):
        with session_scope(engine) as session:
            TicketRepo(session).create(
                org_id=org.id, customer_id=customer.id, channel="web_portal", idempotency_key="dup-1"
            )
