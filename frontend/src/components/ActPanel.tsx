import { useEffect, useState } from "react";

import {
  useApprove,
  useEscalate,
  useExecuteAction,
  useReassign,
  useReject,
  useSaveDraft,
} from "../api/hooks";
import type { CurrentUser, TicketDetail } from "../api/types";
import { ErrorPanel } from "./ErrorPanel";
import { useToasts } from "./Toasts";

// UI-3 region 3 (Act). Nothing here sends anything on its own: `Approve & Send` is the only path
// to the customer and it goes through the workspace API, which records the agent_decision that
// the delivery gateway requires (SAD ADR-008).

const DEPARTMENTS = [
  "technical_support",
  "billing",
  "network_operations",
  "field_service",
  "sales",
  "retention",
  "general",
];

// REQ-WKS: rejection requires a reason code, so the list is fixed rather than free text.
const REASON_CODES = [
  "incorrect_diagnosis",
  "wrong_department",
  "tone_inappropriate",
  "missing_information",
  "policy_violation",
  "customer_already_resolved",
];

export function ActPanel({ ticket, user }: { ticket: TicketDetail; user: CurrentUser | undefined }) {
  const toasts = useToasts();
  const [text, setText] = useState(ticket.draft?.current_text ?? "");
  const [showOriginal, setShowOriginal] = useState(false);
  const [reasonCode, setReasonCode] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [department, setDepartment] = useState(ticket.department ?? "");

  const saveDraft = useSaveDraft(ticket.ticket_id);
  const approve = useApprove(ticket.ticket_id);
  const reject = useReject(ticket.ticket_id);
  const reassign = useReassign(ticket.ticket_id);
  const escalate = useEscalate(ticket.ticket_id);
  const executeAction = useExecuteAction(ticket.ticket_id);

  // Re-seed the editor when the server's draft revision changes, but never clobber an in-progress
  // edit from a background refetch of the same revision.
  useEffect(() => {
    setText(ticket.draft?.current_text ?? "");
  }, [ticket.draft?.id, ticket.draft?.revision]);

  const edited = (ticket.draft?.ai_text ?? "") !== text;
  const terminal = ["RESOLVED", "CLOSED"].includes(ticket.state);
  const canExecute = user?.role === "lead" || user?.role === "admin";

  const onApprove = async () => {
    try {
      if (edited) await saveDraft.mutateAsync(text);
      await approve.mutateAsync();
      toasts.push("Reply approved and sent.", "success");
    } catch {
      toasts.push("The reply could not be sent.", "error");
    }
  };

  const onReject = async () => {
    if (!reasonCode) {
      setReasonError("Select a reason code before rejecting.");
      return;
    }
    setReasonError(null);
    try {
      await reject.mutateAsync(reasonCode);
      toasts.push("Suggestion rejected and returned to the queue.", "success");
    } catch {
      toasts.push("The rejection could not be recorded.", "error");
    }
  };

  return (
    <section aria-labelledby="act-heading" className="space-y-4">
      <h2 id="act-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Act
      </h2>

      {/* UI-7: persistent, not dismissible. */}
      <p role="note" className="rounded border border-amber-400 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
        AI-generated — review before sending.
      </p>

      <div className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Draft reply</h3>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {ticket.draft ? <span>revision {ticket.draft.revision}</span> : null}
            {edited ? <span className="font-semibold text-blue-800">edited</span> : <span>unedited</span>}
            <button type="button" className="underline" onClick={() => setShowOriginal((v) => !v)}>
              {showOriginal ? "Hide AI original" : "Compare with AI original"}
            </button>
          </div>
        </div>

        {ticket.draft ? (
          <>
            <label htmlFor="draft" className="sr-only">
              Draft reply to the customer
            </label>
            <textarea
              id="draft"
              className="input mt-3 min-h-[14rem] font-sans"
              value={text}
              disabled={terminal}
              onChange={(event) => setText(event.target.value)}
            />

            {showOriginal ? (
              <div className="mt-3 rounded border border-slate-200 bg-slate-50 p-3">
                <h4 className="label">AI original (immutable)</h4>
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{ticket.draft.ai_text}</p>
              </div>
            ) : null}

            {ticket.draft.findings?.length ? (
              <ul className="mt-3 space-y-1">
                {ticket.draft.findings.map((finding, index) => (
                  <li
                    key={`${finding.code ?? index}`}
                    className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                  >
                    <span className="font-mono">{finding.code ?? "policy"}</span> — {finding.message ?? "Policy finding"}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : (
          <p className="mt-2 text-sm text-slate-500">
            No draft was generated. Write the reply manually, or reject and reassign the ticket.
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className="btn-primary" onClick={onApprove} disabled={terminal || approve.isPending || !ticket.draft}>
            Approve &amp; Send
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={async () => {
              try {
                await saveDraft.mutateAsync(text);
                toasts.push("Draft saved.", "success");
              } catch {
                toasts.push("The draft could not be saved.", "error");
              }
            }}
            disabled={terminal || saveDraft.isPending || !ticket.draft}
          >
            Save Draft
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={async () => {
              try {
                await escalate.mutateAsync(reasonCode || "agent_escalation");
                toasts.push("Ticket escalated to critical.", "success");
              } catch {
                toasts.push("The escalation could not be recorded.", "error");
              }
            }}
            disabled={terminal || escalate.isPending}
          >
            Escalate
          </button>
          <button type="button" className="btn-danger" onClick={onReject} disabled={terminal || reject.isPending}>
            Reject Suggestion
          </button>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <label className="label" htmlFor="reason">
              Reason code
            </label>
            <select
              id="reason"
              className="input mt-1"
              value={reasonCode}
              onChange={(event) => {
                setReasonCode(event.target.value);
                setReasonError(null);
              }}
              aria-invalid={reasonError ? true : undefined}
              aria-describedby={reasonError ? "reason-error" : undefined}
            >
              <option value="">Select a reason…</option>
              {REASON_CODES.map((code) => (
                <option key={code} value={code}>
                  {code.replace(/_/g, " ")}
                </option>
              ))}
            </select>
            {reasonError ? (
              <p id="reason-error" role="alert" className="mt-1 text-xs font-medium text-red-800">
                {reasonError}
              </p>
            ) : null}
          </div>

          <div>
            <label className="label" htmlFor="reassign-dept">
              Reassign to
            </label>
            <div className="mt-1 flex gap-2">
              <select id="reassign-dept" className="input" value={department} onChange={(e) => setDepartment(e.target.value)}>
                {DEPARTMENTS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn-secondary whitespace-nowrap"
                disabled={terminal || reassign.isPending || !department || department === ticket.department}
                onClick={async () => {
                  try {
                    await reassign.mutateAsync({ department, reason_code: reasonCode || undefined });
                    toasts.push(`Reassigned to ${department}.`, "success");
                  } catch {
                    toasts.push("The reassignment failed.", "error");
                  }
                }}
              >
                Reassign
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="card p-4">
        <h3 className="text-sm font-semibold">Recommended actions</h3>
        {ticket.recommendations.length ? (
          <ul className="mt-3 space-y-2">
            {ticket.recommendations.map((rec) => (
              <li key={rec.id} className="rounded border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-sm">{rec.action_id}</span>
                  <span className="flex items-center gap-2 text-xs">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 uppercase">{rec.status}</span>
                    {rec.requires_supervisor ? (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 uppercase text-amber-900">Supervisor</span>
                    ) : null}
                  </span>
                </div>
                {Object.keys(rec.parameters ?? {}).length ? (
                  <pre className="mt-2 overflow-auto rounded bg-slate-900 p-2 text-[11px] text-slate-100">
                    {JSON.stringify(rec.parameters, null, 2)}
                  </pre>
                ) : null}
                <button
                  type="button"
                  className="btn-secondary mt-2"
                  disabled={terminal || !canExecute || rec.status === "EXECUTED" || executeAction.isPending}
                  title={canExecute ? undefined : "Executing an action requires the lead or admin role"}
                  onClick={async () => {
                    try {
                      await executeAction.mutateAsync(rec.id);
                      toasts.push("Action executed.", "success");
                    } catch {
                      toasts.push("The action could not be executed.", "error");
                    }
                  }}
                >
                  Execute Action
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No action was recommended for this ticket.</p>
        )}
      </div>

      {approve.error ? <ErrorPanel error={approve.error} title="The reply was not sent" /> : null}
      {executeAction.error ? <ErrorPanel error={executeAction.error} title="The action was not executed" /> : null}
    </section>
  );
}
