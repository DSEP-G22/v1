import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useQueue, useQueueSocket } from "../api/hooks";
import type { PriorityBand, QueueRow } from "../api/types";
import { ConfidenceMeter, FlagChips, ModalityIcons, PriorityBadge, SlaCountdown } from "../components/Badges";
import { ErrorPanel } from "../components/ErrorPanel";

// UI-2. Every column is sortable and filterable; critical tickets are pinned above the sort so
// they cannot be hidden by a sort choice, which is the point of a priority band.

type SortKey = "priority" | "sla" | "created" | "department" | "state" | "customer";

const BAND_RANK: Record<PriorityBand, number> = { critical: 0, high: 1, normal: 2, low: 3 };

const COLUMNS: { key: SortKey | null; label: string; className?: string }[] = [
  { key: "priority", label: "Priority" },
  { key: null, label: "Ticket" },
  { key: "customer", label: "Customer" },
  { key: null, label: "Modalities" },
  { key: "department", label: "Department" },
  { key: null, label: "Predicted fault" },
  { key: "sla", label: "SLA" },
  { key: null, label: "Confidence" },
  { key: "state", label: "Status" },
  { key: null, label: "Assignee" },
];

export function QueuePage() {
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useQueue();
  useQueueSocket(true);

  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [ascending, setAscending] = useState(true);
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [band, setBand] = useState("");
  const [state, setState] = useState("");
  const [cursor, setCursor] = useState(0);

  const rows = useMemo(() => data ?? [], [data]);

  const departments = useMemo(
    () => Array.from(new Set(rows.map((r) => r.department).filter(Boolean) as string[])).sort(),
    [rows],
  );
  const states = useMemo(() => Array.from(new Set(rows.map((r) => r.state))).sort(), [rows]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    const filtered = rows.filter((row) => {
      if (department && row.department !== department) return false;
      if (band && row.priority_band !== band) return false;
      if (state && row.state !== state) return false;
      if (!term) return true;
      return (
        row.ticket_id.toLowerCase().includes(term) ||
        row.customer_name.toLowerCase().includes(term) ||
        (row.fault ?? "").toLowerCase().includes(term)
      );
    });

    const direction = ascending ? 1 : -1;
    const sorted = [...filtered].sort((a, b) => direction * compare(a, b, sortKey));

    // Critical tickets are pinned to the top regardless of the chosen sort (UI-2).
    return [
      ...sorted.filter((r) => r.priority_band === "critical"),
      ...sorted.filter((r) => r.priority_band !== "critical"),
    ];
  }, [rows, search, department, band, state, sortKey, ascending]);

  // UI-7 keyboard shortcuts: j/k move, Enter opens, r refreshes. Ignored while typing in a field.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "j") setCursor((c) => Math.min(c + 1, Math.max(visible.length - 1, 0)));
      else if (event.key === "k") setCursor((c) => Math.max(c - 1, 0));
      else if (event.key === "Enter" && visible[cursor]) navigate(`/tickets/${visible[cursor].ticket_id}`);
      else if (event.key === "r") void refetch();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, cursor, navigate, refetch]);

  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load the queue" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Queue</h1>
          <p className="text-sm text-slate-600">
            {visible.length} of {rows.length} tickets · live updates on · shortcuts: j/k move, Enter open, r refresh
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label" htmlFor="q-search">
              Search
            </label>
            <input
              id="q-search"
              className="input mt-1 w-56"
              placeholder="ticket, customer or fault"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <Filter id="q-dept" label="Department" value={department} onChange={setDepartment} options={departments} />
          <Filter id="q-band" label="Priority" value={band} onChange={setBand} options={["critical", "high", "normal", "low"]} />
          <Filter id="q-state" label="Status" value={state} onChange={setState} options={states} />
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="min-w-full text-sm">
          <caption className="sr-only">Prioritised support tickets awaiting agent review</caption>
          <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              {COLUMNS.map((column) => (
                <th key={column.label} scope="col" className="px-3 py-2">
                  {column.key ? (
                    <button
                      type="button"
                      className="font-semibold hover:underline"
                      aria-sort={sortKey === column.key ? (ascending ? "ascending" : "descending") : "none"}
                      onClick={() => {
                        if (sortKey === column.key) setAscending((v) => !v);
                        else {
                          setSortKey(column.key as SortKey);
                          setAscending(true);
                        }
                      }}
                    >
                      {column.label}
                      {sortKey === column.key ? <span aria-hidden="true">{ascending ? " ▲" : " ▼"}</span> : null}
                    </button>
                  ) : (
                    column.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-3 py-8 text-center text-slate-500">
                  Loading queue…
                </td>
              </tr>
            ) : null}

            {!isLoading && visible.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-3 py-8 text-center text-slate-500">
                  No tickets match the current filters.
                </td>
              </tr>
            ) : null}

            {visible.map((row, index) => (
              <tr
                key={row.ticket_id}
                tabIndex={0}
                onFocus={() => setCursor(index)}
                onClick={() => navigate(`/tickets/${row.ticket_id}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    navigate(`/tickets/${row.ticket_id}`);
                  }
                }}
                className={`cursor-pointer border-t border-slate-200 hover:bg-blue-50 ${
                  index === cursor ? "bg-blue-50" : ""
                } ${row.priority_band === "critical" ? "border-l-4 border-l-critical" : ""}`}
              >
                <td className="px-3 py-2">
                  <PriorityBadge band={row.priority_band} score={row.priority_score} />
                </td>
                <td className="px-3 py-2 font-mono text-xs">
                  {row.ticket_id.slice(0, 8)}…
                  <div className="mt-1">
                    <FlagChips flags={row.flags} />
                  </div>
                </td>
                <td className="px-3 py-2">
                  {row.customer_name}
                  <div className="text-xs text-slate-500">{row.channel ?? "—"}</div>
                </td>
                <td className="px-3 py-2">
                  <ModalityIcons modalities={row.modalities} />
                </td>
                <td className="px-3 py-2">{row.department ?? "—"}</td>
                <td className="px-3 py-2 max-w-[16rem] truncate" title={row.fault ?? ""}>
                  {row.fault ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <SlaCountdown dueAt={row.sla_due_at} />
                </td>
                <td className="px-3 py-2">
                  <ConfidenceMeter value={row.diagnosis_confidence ?? row.department_confidence} label="Model confidence" />
                </td>
                <td className="px-3 py-2 text-xs">{row.state}</td>
                <td className="px-3 py-2 text-xs">{row.locked_by ?? <span className="text-slate-400">unassigned</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Filter({
  id,
  label,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <div>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <select id={id} className="input mt-1 w-40" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  );
}

function compare(a: QueueRow, b: QueueRow, key: SortKey): number {
  switch (key) {
    case "priority": {
      const rankA = a.priority_band ? BAND_RANK[a.priority_band] : 9;
      const rankB = b.priority_band ? BAND_RANK[b.priority_band] : 9;
      if (rankA !== rankB) return rankA - rankB;
      return (b.priority_score ?? -1) - (a.priority_score ?? -1);
    }
    case "sla":
      return time(a.sla_due_at) - time(b.sla_due_at);
    case "created":
      return time(a.created_at) - time(b.created_at);
    case "department":
      return (a.department ?? "").localeCompare(b.department ?? "");
    case "state":
      return a.state.localeCompare(b.state);
    case "customer":
      return a.customer_name.localeCompare(b.customer_name);
    default:
      return 0;
  }
}

function time(value: string | null): number {
  return value ? new Date(value).getTime() : Number.MAX_SAFE_INTEGER;
}
