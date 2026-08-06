"""Drives the pipeline in-process (the "same code, different driver" seam of UC-8) over a
synthetic multimodal ticket set, collects per-stage timings from `ticket_state_transition`,
computes the metric set of `evaluation/harness/metrics.py`, and writes JSON + CSV + Markdown to
`evaluation/reports/`.

Usage: APP_PROFILE=stub python -m evaluation.harness.run --n 100
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from libs.domain.contracts.analysis import DraftResponse  # noqa: E402
from libs.domain.contracts.events import Topics  # noqa: E402
from libs.platform.config import get_settings  # noqa: E402
from libs.platform.db import outbox  # noqa: E402
from libs.platform.db.repositories import (  # noqa: E402
    CustomerRepo,
    DiagnosisRepo,
    DraftResponseRepo,
    OrganizationRepo,
    TicketRepo,
)
from libs.platform.db.models import TicketStateTransitionRow  # noqa: E402
from libs.platform.db.session import build_engine, init_db, session_scope  # noqa: E402
from libs.platform.registry import build_ports  # noqa: E402
from services.aggregator_svc.handler import handle_audio_done, handle_image_done, handle_text_done, sweep  # noqa: E402
from services.audio_svc.handler import handle as audio_handle  # noqa: E402
from services.image_svc.handler import handle as image_handle  # noqa: E402
from services.intake_api.handler import InboundFile, create_ticket  # noqa: E402
from services.orchestrator_svc.handler import handle as orchestrator_handle  # noqa: E402
from services.projector_svc.handler import handle_ready as projector_handle  # noqa: E402
from services.response_svc.handler import handle as response_handle  # noqa: E402
from services.routing_svc.handler import handle as routing_handle  # noqa: E402
from services.text_svc.handler import handle as text_handle  # noqa: E402
from services.triage_svc.handler import handle as triage_handle  # noqa: E402
from libs.platform.broker.inprocess import InProcessBroker  # noqa: E402

from evaluation.datasets.synthetic import generate_tickets  # noqa: E402
from evaluation.harness import metrics as m  # noqa: E402


def _wire(broker: InProcessBroker, ports, engine, settings) -> None:
    broker.subscribe(Topics.TICKETS_RAW, "routing_svc", lambda env: routing_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_TEXT_WORK, "text_svc", lambda env: text_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_AUDIO_WORK, "audio_svc", lambda env: audio_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_IMAGE_WORK, "image_svc", lambda env: image_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_TEXT_DONE, "aggregator_svc", lambda env: handle_text_done(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_AUDIO_DONE, "aggregator_svc", lambda env: handle_audio_done(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_IMAGE_DONE, "aggregator_svc", lambda env: handle_image_done(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_AGGREGATED, "triage_svc", lambda env: triage_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_TRIAGED, "orchestrator_svc", lambda env: orchestrator_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_DIAGNOSED, "response_svc", lambda env: response_handle(ports, engine, settings, env))
    broker.subscribe(Topics.TICKETS_READY, "projector_svc", lambda env: projector_handle(ports, engine, settings, env))


def run(n: int, database_path: Path, report_dir: Path) -> dict:
    settings = get_settings()
    engine = build_engine(f"sqlite+pysqlite:///{database_path}")
    init_db(engine)
    ports = build_ports(settings)

    with session_scope(engine) as session:
        org = OrganizationRepo(session).create(name="Eval Harness Org")
        customer = CustomerRepo(session).create(org_id=org.id, name="Eval Harness Customer")
        customer_id = customer.id

    broker = InProcessBroker(max_retries=2)
    _wire(broker, ports, engine, settings)
    broker.start()

    tickets = generate_tickets(n)
    ticket_ids: list[str] = []
    submit_start = time.time()

    try:
        for t in tickets:
            files = []
            if t.audio_path:
                files.append(InboundFile(filename=t.audio_path.name, data=t.audio_path.read_bytes()))
            if t.image_path:
                files.append(InboundFile(filename=t.image_path.name, data=t.image_path.read_bytes()))
            ticket_id = create_ticket(
                ports, engine, customer_id=customer_id, channel="web_portal", text=t.text, files=files, idempotency_key=None
            )
            ticket_ids.append(ticket_id)

        deadline = time.time() + max(30.0, n * 0.5)
        pending = set(ticket_ids)
        while pending and time.time() < deadline:
            outbox.drain(broker, engine)
            sweep(ports, engine, settings)
            with session_scope(engine) as session:
                for ticket_id in list(pending):
                    ticket = TicketRepo(session).get(ticket_id)
                    if ticket is not None and ticket.state in ("READY_FOR_AGENT", "FAILED"):
                        pending.discard(ticket_id)
            time.sleep(0.05)

        wall_s = time.time() - submit_start

        y_true_dept, y_pred_dept = [], []
        fault_pairs: list[tuple[str | None, list[str]]] = []
        citation_lists: list[list[bool]] = []
        edit_distances: list[int] = []
        json_ok: list[bool] = []
        latencies = m.StageLatencies()

        with session_scope(engine) as session:
            for t, ticket_id in zip(tickets, ticket_ids):
                ticket = TicketRepo(session).get(ticket_id)
                if ticket is None:
                    continue

                if ticket.department:
                    y_true_dept.append(t.expected_department)
                    y_pred_dept.append(ticket.department)

                diagnosis = DiagnosisRepo(session).get_latest(ticket_id)
                if diagnosis is not None:
                    predicted_faults = [diagnosis.fault] + list(diagnosis.alternatives) if diagnosis.fault else list(diagnosis.alternatives)
                    fault_pairs.append((t.expected_fault, [f for f in predicted_faults if f]))
                    citations = DiagnosisRepo(session).citations_for(diagnosis.id)
                    if citations:
                        citation_lists.append([c.verified for c in citations])
                    json_ok.append(True)
                else:
                    json_ok.append(False)

                draft = DraftResponseRepo(session).get_latest(ticket_id)
                if draft is not None:
                    domain_draft = DraftResponse(
                        ticket_id=ticket_id, ai_text=draft.ai_text, current_text=draft.current_text
                    )
                    edit_distances.append(domain_draft.diff())

                rows = session.execute(
                    TicketStateTransitionRow.__table__.select().where(TicketStateTransitionRow.ticket_id == ticket_id)
                ).fetchall()
                transitions = [(r.from_state, r.to_state, r.at) for r in rows]
                if transitions:
                    latencies.add_transitions(transitions)

        completed = n - len(pending)
        report = {
            "n_tickets": n,
            "n_completed": completed,
            "n_timed_out": len(pending),
            "wall_s": wall_s,
            "throughput_tickets_per_s": completed / wall_s if wall_s > 0 else float("nan"),
            "department_accuracy": m.department_accuracy(y_true_dept, y_pred_dept),
            "department_macro_f1": m.department_macro_f1(y_true_dept, y_pred_dept),
            "fault_top1_accuracy": m.fault_topk_accuracy(fault_pairs, k=1),
            "fault_top3_accuracy": m.fault_topk_accuracy(fault_pairs, k=3),
            "citation_verification_rate": m.citation_verification_rate(citation_lists),
            "json_validity_rate": m.json_validity_rate(json_ok),
            "stage_latency_ms": latencies.summary(),
        }
        return report
    finally:
        broker.stop()


def write_reports(report: dict, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "e2e_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    with open(report_dir / "e2e_report.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in report.items():
            if key == "stage_latency_ms":
                continue
            writer.writerow([key, value])

    lines = ["# End-to-end evaluation report", ""]
    lines.append(f"- Tickets: {report['n_completed']}/{report['n_tickets']} completed in {report['wall_s']:.1f}s")
    lines.append(f"- Throughput: {report['throughput_tickets_per_s']:.2f} tickets/s")
    lines.append(f"- Department accuracy: {report['department_accuracy']:.3f} (macro-F1 {report['department_macro_f1']:.3f})")
    lines.append(f"- Fault top-1 / top-3 accuracy: {report['fault_top1_accuracy']:.3f} / {report['fault_top3_accuracy']:.3f}")
    lines.append(f"- Citation verification rate: {report['citation_verification_rate']:.3f}")
    lines.append(f"- JSON validity rate: {report['json_validity_rate']:.3f}")
    lines.append("")
    lines.append("## Stage latency (ms)")
    lines.append("")
    lines.append("| stage | n | p50 | p95 | mean |")
    lines.append("|---|---|---|---|---|")
    for stage, s in report["stage_latency_ms"].items():
        lines.append(f"| {stage} | {s['n']} | {s['p50_ms']:.1f} | {s['p95_ms']:.1f} | {s['mean_ms']:.1f} |")

    (report_dir / "e2e_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--db", type=str, default="v1_data/harness.db")
    parser.add_argument("--report-dir", type=str, default="evaluation/reports")
    args = parser.parse_args()

    report = run(args.n, Path(args.db), Path(args.report_dir))
    write_reports(report, Path(args.report_dir))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
