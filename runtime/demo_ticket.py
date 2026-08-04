"""Posts the prototype's sample assets (sample_call.wav, router_red_led.png) plus a text
complaint, then polls until READY_FOR_AGENT and prints the payload, triage, diagnosis, and draft.

Usage: APP_PROFILE=stub python -m runtime.demo_ticket   (or APP_PROFILE=cpu with Ollama running)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from libs.platform.db.repositories import (
    CustomerRepo,
    DiagnosisRepo,
    DraftResponseRepo,
    OrganizationRepo,
    TicketRepo,
    TriageResultRepo,
    UnifiedPayloadRepo,
)
from libs.platform.db.session import session_scope
from runtime.wiring import build_app
from services.intake_api.handler import InboundFile, create_ticket

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_AUDIO = _REPO_ROOT / "ingestion-pipeline-prototype" / "data" / "sample_audio" / "sample_call.wav"
_SAMPLE_IMAGE = _REPO_ROOT / "ingestion-pipeline-prototype" / "data" / "sample_images" / "router_red_led.png"

DEMO_TEXT = (
    "Hi, my router's power light has been solid red since this morning and I have no internet "
    "connection at all. I've already tried unplugging it once. This is the second time this "
    "month, please help."
)


def _ensure_demo_customer(engine) -> str:
    with session_scope(engine) as session:
        org = OrganizationRepo(session).first()
        if org is None:
            org = OrganizationRepo(session).create(name="Demo Org")
        customer = CustomerRepo(session).create(org_id=org.id, name="Demo Customer", segment="standard")
        return customer.id


def _load_inbound_files() -> list[InboundFile]:
    files: list[InboundFile] = []
    if _SAMPLE_AUDIO.exists():
        files.append(InboundFile(filename=_SAMPLE_AUDIO.name, data=_SAMPLE_AUDIO.read_bytes()))
    else:
        print(f"warning: sample audio not found at {_SAMPLE_AUDIO}", file=sys.stderr)
    if _SAMPLE_IMAGE.exists():
        files.append(InboundFile(filename=_SAMPLE_IMAGE.name, data=_SAMPLE_IMAGE.read_bytes()))
    else:
        print(f"warning: sample image not found at {_SAMPLE_IMAGE}", file=sys.stderr)
    return files


def main() -> None:
    app = build_app()
    app.start()

    try:
        customer_id = _ensure_demo_customer(app.engine)
        files = _load_inbound_files()

        ticket_id = create_ticket(
            app.ports,
            app.engine,
            customer_id=customer_id,
            channel="web_portal",
            text=DEMO_TEXT,
            files=files,
            idempotency_key=None,
        )
        print(f"created ticket {ticket_id}")

        deadline = time.time() + 60
        state = None
        while time.time() < deadline:
            with session_scope(app.engine) as session:
                ticket = TicketRepo(session).get(ticket_id)
                state = ticket.state if ticket else None
                if state in ("READY_FOR_AGENT", "FAILED"):
                    break
            time.sleep(0.2)

        print(f"final state: {state}")

        with session_scope(app.engine) as session:
            payload = UnifiedPayloadRepo(session).get_latest(ticket_id)
            triage = TriageResultRepo(session).get_latest(ticket_id)
            diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
            draft = DraftResponseRepo(session).get_latest(ticket_id)

            print("\n--- unified payload ---")
            if payload:
                print(f"partial={payload.partial} flags={payload.flags}")
                print(payload.fused_text)

            print("\n--- triage ---")
            if triage:
                print(f"department={triage.department} band={triage.band} score={triage.priority_score}")

            print("\n--- diagnosis ---")
            if diagnosis:
                print(f"intent={diagnosis.intent} fault={diagnosis.fault} confidence={diagnosis.confidence}")
                print(diagnosis.rationale)

            print("\n--- draft response ---")
            if draft:
                print(draft.ai_text)

        if state != "READY_FOR_AGENT":
            raise SystemExit(f"demo ticket did not reach READY_FOR_AGENT (state={state})")
    finally:
        app.stop()


if __name__ == "__main__":
    main()
