import { useState } from "react";
import { Link } from "react-router-dom";

import { useRecorder } from "../api/useRecorder";
import { fetchSampleAudioFile, useIntakeStatus, useSampleAudio, useSubmitTicket, useTicket } from "../api/hooks";
import { ErrorPanel } from "../components/ErrorPanel";
import { useToasts } from "../components/Toasts";

// A customer-side intake console: submit a complaint with a recorded or uploaded voice message,
// then watch the pipeline resolve it live. The agent workspace consumes tickets but never
// creates them, so without this page the only way to exercise intake is runtime/demo_ticket.py,
// which builds its own in-process app and cannot use a caller's own audio.
//
// Everything else in the app talks to /workspace; this page talks to the intake service at
// /api/v1, which is unauthenticated by design (real customers are not workspace users).

// The happy path through libs/domain/enums.py::TicketState. The post-handoff states (IN_REVIEW,
// RESOLVED, ...) belong to the agent workflow rather than intake, so the tracker stops at the
// point where a ticket becomes the agent's problem.
const PIPELINE_STAGES = ["RECEIVED", "PROCESSING", "AGGREGATED", "TRIAGED", "DIAGNOSED", "READY_FOR_AGENT"];

const CUSTOMER_ID_KEY = "cst.customerId";

/** Index of the state within the tracker. States past handoff still count as complete, so a
 *  ticket an agent has already picked up does not appear to regress. */
function stageIndex(state: string | undefined): number {
  if (!state) return -1;
  const index = PIPELINE_STAGES.indexOf(state);
  if (index >= 0) return index;
  if (state === "FAILED") return -1;
  return PIPELINE_STAGES.length; // IN_REVIEW and later: everything shown is done
}

function ProgressTracker({ state }: { state: string | undefined }) {
  const current = stageIndex(state);
  const failed = state === "FAILED";

  return (
    <ol className="flex flex-wrap gap-2" aria-label="Pipeline progress">
      {PIPELINE_STAGES.map((stage, index) => {
        const done = current > index;
        const active = current === index;
        return (
          <li
            key={stage}
            aria-current={active ? "step" : undefined}
            className={[
              "rounded px-2 py-1 font-mono text-[11px] font-semibold uppercase",
              done ? "bg-green-100 text-green-900" : "",
              active && !failed ? "bg-blue-100 text-blue-900" : "",
              active && failed ? "bg-red-100 text-red-900" : "",
              !done && !active ? "bg-slate-100 text-slate-400" : "",
            ].join(" ")}
          >
            {stage.replace(/_/g, " ")}
          </li>
        );
      })}
    </ol>
  );
}

export function SubmitPage() {
  const toasts = useToasts();
  const recorder = useRecorder();
  const submit = useSubmitTicket();

  // There is no endpoint that lists customers (admin_api exposes users, not customers), so the
  // ID is entered once and remembered rather than fetched.
  const [customerId, setCustomerId] = useState(() => localStorage.getItem(CUSTOMER_ID_KEY) ?? "");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [ticketId, setTicketId] = useState<string | null>(null);
  const [loadingSample, setLoadingSample] = useState<string | null>(null);

  const samples = useSampleAudio();

  const status = useIntakeStatus(ticketId);
  const ready = status.data?.state === "READY_FOR_AGENT";
  // The full view carries the transcript, diagnosis and draft; it only exists once the pipeline
  // has finished, so it stays disabled until then.
  const detail = useTicket(ready && ticketId ? ticketId : "");

  const addFiles = (incoming: FileList | null) => {
    if (incoming) setFiles((existing) => [...existing, ...Array.from(incoming)]);
  };

  const stopRecording = async () => {
    const recorded = await recorder.stop();
    if (recorded) setFiles((existing) => [...existing, recorded]);
  };

  const attachSample = async (id: string) => {
    setLoadingSample(id);
    try {
      const file = await fetchSampleAudioFile(id);
      setFiles((existing) => [...existing, file]);
      setFieldError(null);
    } catch {
      setFieldError("That sample could not be loaded.");
    } finally {
      setLoadingSample(null);
    }
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!customerId.trim()) {
      setFieldError("Enter the customer ID the ticket belongs to.");
      return;
    }
    if (!text.trim() && files.length === 0) {
      setFieldError("Add a description or attach a voice message.");
      return;
    }
    setFieldError(null);
    try {
      const created = await submit.mutateAsync({
        customerId: customerId.trim(),
        channel: "web_portal",
        text: text.trim(),
        files,
      });
      localStorage.setItem(CUSTOMER_ID_KEY, customerId.trim());
      setTicketId(created.ticket_id);
      toasts.push("Ticket submitted. Watching it resolve…", "success");
    } catch {
      toasts.push("The ticket could not be submitted.", "error");
    }
  };

  const startOver = () => {
    setTicketId(null);
    setText("");
    setFiles([]);
    setFieldError(null);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Submit a ticket</h1>

      <form onSubmit={onSubmit} className="card space-y-4 p-4" noValidate>
        <div>
          <label className="label" htmlFor="customer">
            Customer ID
          </label>
          <input
            id="customer"
            className="input mt-1"
            value={customerId}
            onChange={(event) => setCustomerId(event.target.value)}
            placeholder="ULID of an existing customer"
          />
        </div>

        <div>
          <label className="label" htmlFor="complaint">
            What is the problem?
          </label>
          <textarea
            id="complaint"
            className="input mt-1 min-h-[7rem]"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Describe the issue, or leave blank and record a voice message."
          />
        </div>

        <div>
          <span className="label">Voice message</span>
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
                {recorder.state === "encoding" ? "Encoding…" : "Record from microphone"}
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
                  addFiles(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Audio is accepted as WAV, MP3, OGG or FLAC; microphone recordings are converted to WAV
            automatically. Images may be attached alongside.
          </p>
          {recorder.error ? (
            <p role="alert" className="mt-2 text-xs font-medium text-red-800">
              {recorder.error}
            </p>
          ) : null}
        </div>

        {samples.data?.length ? (
          <div>
            <span className="label">Or attach a sample utterance</span>
            <p className="mt-1 text-xs text-slate-500">
              Real 8 kHz call-centre speech from minds14, one per intent. Each is a different
              recording, so successive tickets exercise the pipeline on genuinely different input
              rather than re-running one clip.
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {samples.data.map((sample) => (
                <button
                  key={sample.id}
                  type="button"
                  className="rounded border border-slate-300 px-2 py-1 font-mono text-[11px] hover:bg-slate-50 disabled:opacity-50"
                  disabled={loadingSample !== null}
                  onClick={() => void attachSample(sample.id)}
                  title={`${sample.id} (${(sample.bytes / 1024).toFixed(0)} KB)`}
                >
                  {loadingSample === sample.id ? "loading…" : sample.intent.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {files.length ? (
          <ul className="space-y-1">
            {files.map((file, index) => (
              <li
                key={`${file.name}-${index}`}
                className="flex items-center justify-between rounded border border-slate-200 px-3 py-2 text-sm"
              >
                <span className="truncate">
                  {file.name}{" "}
                  <span className="font-mono text-xs text-slate-500">
                    ({(file.size / 1024).toFixed(0)} KB)
                  </span>
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

        {fieldError ? (
          <p role="alert" className="text-xs font-medium text-red-800">
            {fieldError}
          </p>
        ) : null}
        {submit.error ? <ErrorPanel error={submit.error} title="Submission failed" /> : null}

        <div className="flex gap-2">
          <button type="submit" className="btn-primary" disabled={submit.isPending}>
            {submit.isPending ? "Submitting…" : "Submit ticket"}
          </button>
          {ticketId ? (
            <button type="button" className="btn-secondary" onClick={startOver}>
              Submit another
            </button>
          ) : null}
        </div>
      </form>

      {ticketId ? (
        <div className="card space-y-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">
              Ticket <span className="font-mono text-xs">{ticketId}</span>
            </h2>
            <Link className="text-xs font-semibold text-blue-800" to={`/tickets/${ticketId}`}>
              Open in workspace
            </Link>
          </div>

          <ProgressTracker state={status.data?.state} />

          {status.data?.state === "FAILED" ? (
            <p role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
              The pipeline could not process this ticket. Check the API logs, or the DLQ on the
              admin page, for the failing stage.
            </p>
          ) : null}

          {status.data?.department ? (
            <p className="text-sm">
              Routed to <strong>{status.data.department}</strong> with priority{" "}
              <strong>{status.data.priority_band}</strong>{" "}
              <span className="font-mono text-xs text-slate-500">({status.data.priority_score})</span>
            </p>
          ) : null}

          {!ready && status.data?.state !== "FAILED" ? (
            <p className="text-sm text-slate-500">Processing… transcribing audio and diagnosing.</p>
          ) : null}

          {detail.data?.payload ? (
            <section>
              <h3 className="text-xs font-semibold uppercase text-slate-600">Transcript and fused text</h3>
              <p className="mt-1 whitespace-pre-wrap text-sm">{detail.data.payload.fused_text}</p>
              {detail.data.payload.flags.length ? (
                <p className="mt-1 font-mono text-xs text-slate-500">
                  flags: {detail.data.payload.flags.join(", ")}
                </p>
              ) : null}
            </section>
          ) : null}

          {detail.data?.diagnosis ? (
            <section>
              <h3 className="text-xs font-semibold uppercase text-slate-600">Diagnosis</h3>
              <p className="mt-1 text-sm">
                <strong>{detail.data.diagnosis.fault ?? detail.data.diagnosis.intent}</strong>{" "}
                <span className="font-mono text-xs text-slate-500">
                  (confidence {detail.data.diagnosis.confidence.toFixed(2)})
                </span>
              </p>
              <p className="mt-1 text-sm text-slate-700">{detail.data.diagnosis.rationale}</p>
            </section>
          ) : null}

          {detail.data?.draft ? (
            <section>
              <h3 className="text-xs font-semibold uppercase text-slate-600">Proposed reply</h3>
              <p className="mt-1 whitespace-pre-wrap text-sm">{detail.data.draft.current_text}</p>
              {!detail.data.draft.ai_generated ? (
                <p className="mt-1 text-xs text-amber-800">
                  Generated from a template, not a language model — the configured LLM was
                  unreachable.
                </p>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
