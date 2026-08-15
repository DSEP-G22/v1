import { useState } from "react";

import type { Citation, TicketDetail } from "../api/types";
import { ConfidenceMeter, PriorityBadge } from "./Badges";

// UI-3 region 2 (Diagnosis): department, priority score with its contributing signals, intent,
// fault with confidence, and every retrieved citation expandable to its source excerpt.

export function DiagnosisPanel({ ticket }: { ticket: TicketDetail }) {
  const { triage, diagnosis } = ticket;

  return (
    <section aria-labelledby="diagnosis-heading" className="space-y-4">
      <h2 id="diagnosis-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Diagnosis
      </h2>

      <div className="card p-4">
        <h3 className="text-sm font-semibold">Triage</h3>
        {triage ? (
          <dl className="mt-3 space-y-2 text-sm">
            <Row label="Department">
              <span className="flex items-center gap-2">
                {triage.department}
                <ConfidenceMeter value={triage.department_confidence} label="Department confidence" />
              </span>
            </Row>
            <Row label="Priority">
              <PriorityBadge band={triage.band} score={triage.priority_score} />
            </Row>
            <Row label="Sentiment">{triage.sentiment}</Row>
          </dl>
        ) : (
          <p className="mt-2 text-sm text-slate-500">Triage has not completed for this ticket.</p>
        )}

        {triage?.signals?.length ? (
          <div className="mt-3">
            <h4 className="label">Contributing signals</h4>
            <ul className="mt-2 space-y-1">
              {triage.signals.map((signal, index) => {
                const name = String(signal.name ?? signal.label ?? `signal ${index + 1}`);
                const weight = typeof signal.weight === "number" ? signal.weight : null;
                return (
                  <li key={`${name}-${index}`} className="flex items-center justify-between gap-3 text-sm">
                    <span className="text-slate-700">{name}</span>
                    <span className="flex items-center gap-2">
                      {signal.value !== undefined ? (
                        <span className="font-mono text-xs text-slate-500">{String(signal.value)}</span>
                      ) : null}
                      {weight !== null ? (
                        <span className="h-1.5 w-24 overflow-hidden rounded bg-slate-200">
                          <span className="block h-full bg-blue-700" style={{ width: `${Math.min(Math.abs(weight), 100)}%` }} />
                        </span>
                      ) : null}
                      {weight !== null ? <span className="w-8 text-right font-mono text-xs">{weight}</span> : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>

      <div className="card p-4">
        <h3 className="text-sm font-semibold">Fault prediction</h3>
        {diagnosis ? (
          <>
            {diagnosis.needs_human_diagnosis ? (
              <p className="mt-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Confidence is below the configured threshold, the System is not asserting this fault. Diagnose manually.
              </p>
            ) : null}
            <dl className="mt-3 space-y-2 text-sm">
              <Row label="Intent">{diagnosis.intent}</Row>
              <Row label="Fault">
                <span className="flex items-center gap-2">
                  {diagnosis.fault ?? ","}
                  <ConfidenceMeter value={diagnosis.confidence} label="Fault confidence" />
                </span>
              </Row>
            </dl>
            <div className="mt-3">
              <h4 className="label">Rationale</h4>
              <p className="mt-1 whitespace-pre-wrap text-sm text-slate-800">{diagnosis.rationale}</p>
            </div>
            <Citations citations={diagnosis.citations} />
          </>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No diagnosis was produced for this ticket.</p>
        )}
      </div>
    </section>
  );
}

function Citations({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!citations.length) {
    return (
      <p className="mt-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        No supporting procedure was retrieved. Treat the reply as unsourced.
      </p>
    );
  }

  return (
    <div className="mt-4">
      <h4 className="label">Retrieved procedures ({citations.length})</h4>
      <ul className="mt-2 space-y-2">
        {citations.map((citation) => (
          <li key={citation.chunk_id} className="rounded border border-slate-200">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm"
              aria-expanded={expanded === citation.chunk_id}
              onClick={() => setExpanded((current) => (current === citation.chunk_id ? null : citation.chunk_id))}
            >
              <span className="flex items-center gap-2">
                <span className="font-mono text-xs">{citation.chunk_id}</span>
                <span className="text-xs text-slate-500">v{citation.chunk_version}</span>
                {citation.verified ? (
                  <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-green-900">
                    Verified
                  </span>
                ) : (
                  <span
                    className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-900"
                    title="This citation was not present in the retrieved context and was dropped from the grounding check"
                  >
                    Unverified
                  </span>
                )}
              </span>
              <span className="flex items-center gap-2 text-xs text-slate-500">
                <ConfidenceMeter value={citation.relevance} label="Relevance" />
                <span aria-hidden="true">{expanded === citation.chunk_id ? "▲" : "▼"}</span>
              </span>
            </button>
            {expanded === citation.chunk_id ? (
              <p className="border-t border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800">
                {citation.excerpt ?? "The source passage is no longer available at this version."}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  );
}
