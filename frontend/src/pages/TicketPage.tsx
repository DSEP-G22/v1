import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useLockTicket, useMe, useTicket } from "../api/hooks";
import { ActPanel } from "../components/ActPanel";
import { PriorityBadge } from "../components/Badges";
import { DiagnosisPanel } from "../components/DiagnosisPanel";
import { ErrorPanel } from "../components/ErrorPanel";
import { EvidencePanel } from "../components/EvidencePanel";
import { useToasts } from "../components/Toasts";

// UI-3: the three-region triage workspace. The regions sit side by side on a wide screen and
// stack on a narrow one; the SRS requires 1366×768 to be usable, which the 2-column breakpoint
// covers.

export function TicketPage() {
  const { ticketId = "" } = useParams();
  const navigate = useNavigate();
  const toasts = useToasts();
  const { data: user } = useMe();
  const { data: ticket, isLoading, error, refetch } = useTicket(ticketId);
  const lock = useLockTicket(ticketId);

  // Opening a ticket takes the lock, which is what stops two agents from replying to the same
  // customer. A 409 means someone else holds it; the ticket stays readable.
  useEffect(() => {
    if (!ticketId) return;
    lock.mutate(undefined, {
      onError: () => toasts.push("This ticket is locked by another agent — opened read-only.", "info"),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId]);

  // UI-7 shortcuts for the high-frequency operations. Escape returns to the queue.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "Escape") navigate("/queue");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  if (isLoading) return <p className="text-sm text-slate-500">Loading ticket…</p>;
  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load the ticket" />;
  if (!ticket) return null;

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div>
          <h1 className="font-mono text-sm font-semibold">{ticket.ticket_id}</h1>
          <p className="text-xs text-slate-600">
            {ticket.customer?.name ?? "unknown customer"}
            {ticket.customer?.segment ? ` · ${ticket.customer.segment}` : ""} · {ticket.channel ?? "—"} ·{" "}
            {ticket.created_at ? new Date(ticket.created_at).toLocaleString() : "—"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {ticket.payload?.partial ? (
            <span className="rounded border border-amber-400 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900">
              Partial payload — a modality is missing
            </span>
          ) : null}
          <PriorityBadge band={ticket.priority_band} score={ticket.priority_score} />
          <span className="rounded bg-slate-100 px-2 py-1 text-xs font-medium">{ticket.state}</span>
          <button type="button" className="btn-secondary" onClick={() => navigate("/queue")}>
            Back to queue
          </button>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <EvidencePanel ticket={ticket} />
        <DiagnosisPanel ticket={ticket} />
        <ActPanel ticket={ticket} user={user} />
      </div>

      {ticket.decisions.length ? (
        <div className="card p-4">
          <h2 className="text-sm font-semibold">Decision history</h2>
          <ol className="mt-2 space-y-1 text-sm">
            {ticket.decisions.map((decision) => (
              <li key={decision.id} className="flex flex-wrap gap-3 text-slate-700">
                <span className="font-mono text-xs text-slate-500">
                  {decision.at ? new Date(decision.at).toLocaleString() : "—"}
                </span>
                <span className="font-medium">{decision.type}</span>
                {decision.reason_code ? <span className="text-xs text-slate-500">{decision.reason_code}</span> : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}
