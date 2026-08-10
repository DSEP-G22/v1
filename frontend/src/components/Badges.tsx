import type { PriorityBand } from "../api/types";

// UI-7: "priority never encoded by colour alone". Each band carries a glyph and a written label
// in addition to its colour, so the ranking survives greyscale printing and colour-blindness.

const BAND_STYLE: Record<PriorityBand, { className: string; glyph: string; label: string }> = {
  critical: { className: "border-critical text-critical bg-red-50", glyph: "▲▲", label: "Critical" },
  high: { className: "border-high text-high bg-orange-50", glyph: "▲", label: "High" },
  normal: { className: "border-normal text-normal bg-blue-50", glyph: "■", label: "Normal" },
  low: { className: "border-low text-low bg-slate-100", glyph: "▼", label: "Low" },
};

export function PriorityBadge({ band, score }: { band: PriorityBand | null; score?: number | null }) {
  if (!band) {
    return <span className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-500">Unscored</span>;
  }
  const style = BAND_STYLE[band];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-semibold ${style.className}`}
    >
      <span aria-hidden="true">{style.glyph}</span>
      <span>{style.label}</span>
      {score !== null && score !== undefined ? <span className="font-mono font-normal">{score}</span> : null}
    </span>
  );
}

/** Confidence shown as a number plus a bar; the number is what makes it accessible, the bar is
 *  what makes it scannable. */
export function ConfidenceMeter({ value, label }: { value: number | null | undefined; label: string }) {
  if (value === null || value === undefined) return <span className="text-xs text-slate-400">n/a</span>;
  const percent = Math.round(value * 100);
  const tone = percent >= 75 ? "bg-green-600" : percent >= 50 ? "bg-amber-500" : "bg-red-600";
  return (
    <span className="inline-flex items-center gap-2" title={`${label}: ${percent}%`}>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200">
        <span className={`block h-full ${tone}`} style={{ width: `${percent}%` }} />
      </span>
      <span className="font-mono text-xs">{percent}%</span>
    </span>
  );
}

export function ModalityIcons({ modalities }: { modalities: string[] }) {
  const has = (m: string) => modalities.includes(m);
  const item = (present: boolean, glyph: string, label: string) => (
    <span
      key={label}
      title={present ? `${label} present` : `no ${label}`}
      aria-label={present ? `${label} present` : `no ${label}`}
      className={present ? "text-slate-800" : "text-slate-300"}
    >
      {glyph}
    </span>
  );
  return (
    <span className="inline-flex gap-1 text-sm">
      {item(has("text"), "✎", "text")}
      {item(has("audio"), "♪", "audio")}
      {item(has("image"), "▣", "image")}
    </span>
  );
}

export function FlagChips({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {flags.map((flag) => (
        <span
          key={flag}
          className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] uppercase text-amber-900"
          title="Pipeline flag raised on this ticket"
        >
          {flag}
        </span>
      ))}
    </span>
  );
}

/** UI-2 SLA countdown. Renders overdue explicitly rather than as a negative number. */
export function SlaCountdown({ dueAt }: { dueAt: string | null }) {
  if (!dueAt) return <span className="text-xs text-slate-400">—</span>;
  const minutes = (new Date(dueAt).getTime() - Date.now()) / 60000;
  if (minutes < 0) {
    return <span className="text-xs font-semibold text-critical">Overdue {formatMinutes(-minutes)}</span>;
  }
  const tone = minutes < 60 ? "text-critical font-semibold" : minutes < 240 ? "text-high" : "text-slate-600";
  return <span className={`text-xs ${tone}`}>{formatMinutes(minutes)} left</span>;
}

function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(1)}h`;
  return `${Math.round(hours / 24)}d`;
}
