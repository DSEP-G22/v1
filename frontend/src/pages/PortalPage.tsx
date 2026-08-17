import { useState } from "react";

import { apiUrl } from "../api/client";
import { fetchSampleAudioFile, useIntakeStatus, useSampleAudio } from "../api/hooks";
import { useRecorder } from "../api/useRecorder";

// The customer-facing portal: raise a support ticket and watch it being handled. Public by
// design — it sits outside RequireAuth, because a customer is not a workspace user and has no
// bearer token.
//
// It differs from /submit, the agent-side form, in two ways that matter. It identifies the
// customer by the email they type rather than a ULID nobody outside the database knows, and it
// shows only what a customer should see: that the report arrived, was understood, and was routed.
// The internal diagnosis, confidence scores, priority band and the draft reply are deliberately
// withheld — a draft is not an answer until an agent has approved it, and showing one here would
// read as a commitment the business has not made.

/** Customer-visible progress. The pipeline's own states are internal vocabulary, so they are
 *  collapsed into three things a person actually cares about. */
const STEPS = [
  { key: "received", label: "Report received" },
  { key: "understood", label: "Understood" },
  { key: "routed", label: "Assigned to a specialist" },
];

function stepFor(state: string | undefined): number {
  switch (state) {
    case undefined:
      return -1;
    case "RECEIVED":
    case "PROCESSING":
      return 0;
    case "AGGREGATED":
      return 1;
    case "FAILED":
      return -1;
    default:
      // TRIAGED and everything after it means a department has been chosen.
      return 2;
  }
}

export function PortalPage() {
  const recorder = useRecorder();
  const samples = useSampleAudio();

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingSample, setLoadingSample] = useState<string | null>(null);
  const [ticketId, setTicketId] = useState<string | null>(null);

  const status = useIntakeStatus(ticketId);
  const currentStep = stepFor(status.data?.state);
  const failed = status.data?.state === "FAILED";

  const attachSample = async (id: string) => {
    setLoadingSample(id);
    try {
      const file = await fetchSampleAudioFile(id);
      setFiles((existing) => [...existing, file]);
      setError(null);
    } catch {
      setError("That example could not be loaded.");
    } finally {
      setLoadingSample(null);
    }
  };

  const stopRecording = async () => {
    const recorded = await recorder.stop();
    if (recorded) setFiles((existing) => [...existing, recorded]);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email.includes("@")) {
      setError("Enter the email address we should reply to.");
      return;
    }
    if (!text.trim() && files.length === 0) {
      setError("Describe the problem, or record a voice message.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const form = new FormData();
      form.append("email", email.trim());
      form.append("name", name.trim());
      form.append("text", text.trim());
      files.forEach((file) => form.append("files", file));

      // Posted with fetch rather than the shared api client: that client attaches the agent
      // bearer token and clears it on a 401, neither of which is wanted on a public page.
      const response = await fetch(apiUrl("/api/v1/portal/tickets"), { method: "POST", body: form });
      if (!response.ok) throw new Error(String(response.status));
      const created = (await response.json()) as { ticket_id: string };
      setTicketId(created.ticket_id);
    } catch {
      setError("We could not submit your report. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const startOver = () => {
    setTicketId(null);
    setText("");
    setFiles([]);
    setError(null);
  };

  if (ticketId) {
    return (
      <Shell>
        <h1 className="text-lg font-semibold">Thank you, your report has been received</h1>
        <p className="mt-1 text-sm text-slate-600">
          Your reference is <span className="font-mono text-xs">{ticketId}</span>. Quote it if you
          contact us about this issue.
        </p>

        <ol className="mt-6 space-y-2">
          {STEPS.map((step, index) => {
            const done = currentStep > index;
            const active = currentStep === index;
            return (
              <li key={step.key} className="flex items-center gap-3 text-sm">
                <span
                  aria-hidden
                  className={[
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                    done ? "bg-green-600 text-white" : "",
                    active ? "bg-blue-600 text-white" : "",
                    !done && !active ? "bg-slate-200 text-slate-500" : "",
                  ].join(" ")}
                >
                  {done ? "✓" : index + 1}
                </span>
                <span className={done || active ? "text-slate-900" : "text-slate-400"}>{step.label}</span>
                {active ? <span className="text-xs text-slate-500">in progress…</span> : null}
              </li>
            );
          })}
        </ol>

        {failed ? (
          <p role="alert" className="mt-6 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            We received your report but could not process it automatically. It has been kept, and
            someone will pick it up manually.
          </p>
        ) : null}

        {status.data?.department && !failed ? (
          <p className="mt-6 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
            Assigned to our <strong>{status.data.department.replace(/_/g, " ")}</strong> team. They
            will reply to <strong>{email}</strong>.
          </p>
        ) : null}

        <button type="button" className="btn-secondary mt-6" onClick={startOver}>
          Report another problem
        </button>
      </Shell>
    );
  }

  return (
    <Shell>
      <h1 className="text-lg font-semibold">Contact support</h1>
      <p className="mt-1 text-sm text-slate-600">
        Tell us what is wrong. You can type it, record a voice message, or attach a photo.
      </p>

      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="email">
              Your email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              className="input mt-1"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="label" htmlFor="name">
              Your name <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <input
              id="name"
              autoComplete="name"
              className="input mt-1"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
        </div>

        <div>
          <label className="label" htmlFor="problem">
            What is the problem?
          </label>
          <textarea
            id="problem"
            className="input mt-1 min-h-[8rem]"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="For example: my internet has been down since last night and the router light is red."
          />
        </div>

        <div>
          <span className="label">Voice message or photo</span>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {recorder.state === "recording" ? (
              <>
                <button type="button" className="btn-primary" onClick={() => void stopRecording()}>
                  Stop recording ({recorder.seconds}s)
                </button>
                <button type="button" className="btn-secondary" onClick={recorder.cancel}>
                  Discard
                </button>
                <span aria-hidden className="h-2 w-2 animate-pulse rounded-full bg-red-600" />
              </>
            ) : (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => void recorder.start()}
                disabled={recorder.state === "encoding"}
              >
                {recorder.state === "encoding" ? "Processing…" : "Record a voice message"}
              </button>
            )}

            <label className="btn-secondary cursor-pointer">
              Attach a file
              <input
                type="file"
                multiple
                accept="audio/*,image/*"
                className="hidden"
                onChange={(event) => {
                  if (event.target.files) setFiles((e) => [...e, ...Array.from(event.target.files!)]);
                  event.target.value = "";
                }}
              />
            </label>
          </div>
          {recorder.error ? (
            <p role="alert" className="mt-2 text-xs font-medium text-red-800">
              {recorder.error}
            </p>
          ) : null}
        </div>

        {samples.data?.length ? (
          <details className="rounded border border-slate-200 px-3 py-2">
            <summary className="cursor-pointer text-xs font-semibold text-slate-600">
              No microphone? Use an example recording
            </summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {samples.data.map((sample) => (
                <button
                  key={sample.id}
                  type="button"
                  className="rounded border border-slate-300 px-2 py-1 font-mono text-[11px] hover:bg-slate-50 disabled:opacity-50"
                  disabled={loadingSample !== null}
                  onClick={() => void attachSample(sample.id)}
                >
                  {loadingSample === sample.id ? "loading…" : sample.intent.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </details>
        ) : null}

        {files.length ? (
          <ul className="space-y-1">
            {files.map((file, index) => (
              <li
                key={`${file.name}-${index}`}
                className="flex items-center justify-between rounded border border-slate-200 px-3 py-2 text-sm"
              >
                <span className="truncate">
                  {file.name} <span className="font-mono text-xs text-slate-500">({(file.size / 1024).toFixed(0)} KB)</span>
                </span>
                <button
                  type="button"
                  className="text-xs font-semibold text-red-800"
                  onClick={() => setFiles((existing) => existing.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {error ? (
          <p role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
            {error}
          </p>
        ) : null}

        <button type="submit" className="btn-primary w-full justify-center" disabled={busy}>
          {busy ? "Sending…" : "Send report"}
        </button>
      </form>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <div className="card w-full max-w-xl p-8">{children}</div>
    </div>
  );
}
