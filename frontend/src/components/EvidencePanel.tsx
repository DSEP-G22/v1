import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";

import { fetchMediaObjectUrl } from "../api/client";
import type { Attachment, ProvenanceEntry, TicketDetail } from "../api/types";
import { ConfidenceMeter } from "./Badges";

// UI-3 region 1 (Evidence): original text, audio with its transcript beside it and per-segment
// confidence shading, images with the VLM summary, and the fused text with provenance labels.

export function EvidencePanel({ ticket }: { ticket: TicketDetail }) {
  const audio = ticket.attachments.filter((a) => a.modality === "audio");
  const images = ticket.attachments.filter((a) => a.modality === "image");

  return (
    <section aria-labelledby="evidence-heading" className="space-y-4">
      <h2 id="evidence-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Evidence
      </h2>

      <div className="card p-4">
        <h3 className="text-sm font-semibold">Customer text</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm text-slate-800">
          {ticket.payload?.original_text?.trim() || <span className="text-slate-400">No text was submitted.</span>}
        </p>
      </div>

      {audio.map((attachment) => (
        <AudioEvidence key={attachment.id} attachment={attachment} />
      ))}

      {images.map((attachment) => (
        <ImageEvidence key={attachment.id} attachment={attachment} />
      ))}

      {ticket.payload ? (
        <FusedText fusedText={ticket.payload.fused_text} provenance={ticket.payload.provenance} />
      ) : null}
    </section>
  );
}

function AudioEvidence({ attachment }: { attachment: Attachment }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const waveRef = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let disposed = false;

    const container = containerRef.current;
    if (!container) return;

    void (async () => {
      try {
        objectUrl = await fetchMediaObjectUrl(attachment.content_url);
        if (disposed) return;
        const wave = WaveSurfer.create({
          container,
          height: 64,
          waveColor: "#94a3b8",
          progressColor: "#1d4ed8",
          cursorColor: "#0f172a",
        });
        wave.load(objectUrl);
        wave.on("play", () => setPlaying(true));
        wave.on("pause", () => setPlaying(false));
        wave.on("timeupdate", (t: number) => setCurrentTime(t));
        waveRef.current = wave;
      } catch {
        if (!disposed) setLoadError("The audio could not be loaded.");
      }
    })();

    return () => {
      disposed = true;
      waveRef.current?.destroy();
      waveRef.current = null;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.content_url]);

  const transcript = attachment.transcript;

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Audio · {attachment.original_filename}</h3>
        {transcript ? (
          <div className="flex items-center gap-3 text-xs text-slate-600">
            <span>{transcript.language}</span>
            <span>{transcript.duration_s.toFixed(1)}s</span>
            <span>sentiment: {transcript.acoustic_sentiment}</span>
            <ConfidenceMeter value={transcript.confidence} label="ASR confidence" />
          </div>
        ) : null}
      </div>

      {transcript?.low_confidence ? (
        <p className="mt-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Low transcription confidence, verify the passage against the audio before relying on it.
        </p>
      ) : null}

      <div ref={containerRef} className="mt-3" />
      {loadError ? <p className="mt-2 text-xs text-red-800">{loadError}</p> : null}

      <div className="mt-2 flex items-center gap-2">
        <button type="button" className="btn-secondary" onClick={() => waveRef.current?.playPause()}>
          {playing ? "Pause" : "Play"}
        </button>
        <span className="font-mono text-xs text-slate-500">{currentTime.toFixed(1)}s</span>
      </div>

      {transcript ? (
        <div className="mt-3 max-h-56 overflow-y-auto rounded border border-slate-200 p-3 text-sm leading-relaxed">
          {transcript.segments.length ? (
            transcript.segments.map((segment, index) => {
              const active = currentTime >= segment.start_s && currentTime < segment.end_s;
              return (
                <button
                  type="button"
                  key={`${segment.start_s}-${index}`}
                  onClick={() => waveRef.current?.setTime(segment.start_s)}
                  title={`confidence ${(segment.confidence * 100).toFixed(0)}% · click to seek`}
                  className={`mr-1 rounded px-0.5 text-left ${active ? "ring-2 ring-blue-600" : ""}`}
                  style={{ backgroundColor: shadeForConfidence(segment.confidence) }}
                >
                  {segment.text}
                </button>
              );
            })
          ) : (
            <p>{transcript.text}</p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-sm text-slate-500">No transcript was produced for this attachment.</p>
      )}
    </div>
  );
}

/** Lower confidence is shaded more strongly, so a doubtful passage is visible at a glance while
 *  the text itself stays at full contrast (UI-7 requires the meaning not to depend on colour, and
 *  the per-segment percentage is in the tooltip). */
function shadeForConfidence(confidence: number): string {
  if (confidence >= 0.85) return "transparent";
  if (confidence >= 0.7) return "rgba(251, 191, 36, 0.18)";
  if (confidence >= 0.5) return "rgba(251, 146, 60, 0.28)";
  return "rgba(248, 113, 113, 0.35)";
}

function ImageEvidence({ attachment }: { attachment: Attachment }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let disposed = false;
    void (async () => {
      try {
        objectUrl = await fetchMediaObjectUrl(attachment.content_url);
        if (!disposed) setUrl(objectUrl);
      } catch {
        if (!disposed) setUrl(null);
      }
    })();
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.content_url]);

  const summary = attachment.visual_summary;

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Image · {attachment.original_filename}</h3>
        {summary ? (
          <div className="flex items-center gap-3 text-xs text-slate-600">
            <span className="font-mono">{summary.prompt_template}</span>
            <ConfidenceMeter value={summary.confidence} label="VLM confidence" />
          </div>
        ) : null}
      </div>

      {summary?.low_confidence ? (
        <p className="mt-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Low extraction confidence, check the image before relying on the extracted fields.
        </p>
      ) : null}

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div>
          {url ? (
            <img src={url} alt={`Customer-supplied evidence: ${attachment.original_filename}`} className="max-h-64 rounded border border-slate-200 object-contain" />
          ) : (
            <div className="flex h-40 items-center justify-center rounded border border-dashed border-slate-300 text-sm text-slate-500">
              Image unavailable
            </div>
          )}
        </div>
        <div>
          <p className="text-sm text-slate-800">{summary?.summary_text ?? "No visual summary was produced."}</p>
          {summary && Object.keys(summary.extracted_fields ?? {}).length ? (
            <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-900 p-2 text-[11px] leading-snug text-slate-100">
              {JSON.stringify(summary.extracted_fields, null, 2)}
            </pre>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** The fused text is what every cognitive stage actually consumed, so each fragment is labelled
 *  with the modality and model that produced it (SAD §9.3 provenance). */
function FusedText({ fusedText, provenance }: { fusedText: string; provenance: ProvenanceEntry[] }) {
  const [open, setOpen] = useState(false);
  const ordered = [...(provenance ?? [])].sort((a, b) => a.span[0] - b.span[0]);

  return (
    <div className="card p-4">
      <button type="button" className="flex w-full items-center justify-between" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <h3 className="text-sm font-semibold">Fused text with provenance</h3>
        <span className="text-xs text-slate-500">{open ? "Hide" : "Show"}</span>
      </button>

      {open ? (
        <div className="mt-3 space-y-3">
          {ordered.length ? (
            ordered.map((entry, index) => (
              <div key={`${entry.source}-${index}`} className="rounded border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono uppercase">{entry.modality}</span>
                  <span className="font-mono">{entry.source}</span>
                  {entry.model_version ? <span className="font-mono">{entry.model_version}</span> : null}
                  <ConfidenceMeter value={entry.confidence} label="Fragment confidence" />
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm">{fusedText.slice(entry.span[0], entry.span[1])}</p>
              </div>
            ))
          ) : (
            <p className="whitespace-pre-wrap text-sm">{fusedText}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
