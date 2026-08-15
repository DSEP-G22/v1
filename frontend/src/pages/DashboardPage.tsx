import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";

import { useDashboard } from "../api/hooks";
import { ErrorPanel } from "../components/ErrorPanel";

// UI-4. Queue depth and ageing per queue, the SLA-breach-risk list, agent workload, and the
// aggregate AI acceptance / edit / rejection rates.

const AGEING_LABELS: Record<string, string> = {
  lt_1h: "< 1h",
  h1_4: "1-4h",
  h4_24: "4-24h",
  gt_24h: "> 24h",
};

const BAND_COLOURS: Record<string, string> = {
  critical: "#b91c1c",
  high: "#c2410c",
  normal: "#1d4ed8",
  low: "#475569",
  unknown: "#94a3b8",
};

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useDashboard();

  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load the dashboard" />;
  if (isLoading || !data) return <p className="text-sm text-slate-500">Loading dashboard…</p>;

  const ageing = Object.entries(data.ageing).map(([key, value]) => ({ bucket: AGEING_LABELS[key] ?? key, tickets: value }));
  const bands = Object.entries(data.queue_depth_by_band).map(([band, value]) => ({ band, tickets: value }));
  const outcomes = data.ai_outcomes;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Supervisor dashboard</h1>
        <p className="text-sm text-slate-600">Generated {new Date(data.generated_at).toLocaleString()}</p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Stat label="Open tickets" value={data.queue_depth_by_department.reduce((sum, d) => sum + d.open, 0)} />
        <Stat label="Reviewed by an agent" value={outcomes.reviewed} />
        <Stat label="AI acceptance rate" value={percent(outcomes.acceptance_rate)} hint={`${outcomes.approved} approved`} />
        <Stat label="Edit rate" value={percent(outcomes.edit_rate)} hint={`${outcomes.approved_edited} edited before sending`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card p-4">
          <h2 className="text-sm font-semibold">Queue depth by department</h2>
          <div className="mt-3 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.queue_depth_by_department}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="department" tick={{ fontSize: 11 }} interval={0} angle={-15} textAnchor="end" height={60} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="open" name="Open" fill="#1d4ed8" />
                <Bar dataKey="total" name="Total" fill="#94a3b8" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold">Open tickets by priority band</h2>
          <div className="mt-3 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bands}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="band" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="tickets" name="Tickets">
                  {bands.map((entry) => (
                    <Cell key={entry.band} fill={BAND_COLOURS[entry.band] ?? "#94a3b8"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold">Queue ageing</h2>
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={ageing}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="tickets" name="Tickets" fill="#0f766e" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold">Agent workload</h2>
          {data.agent_workload.length ? (
            <table className="mt-3 w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th scope="col" className="py-1">Agent</th>
                  <th scope="col" className="py-1">Tickets held</th>
                </tr>
              </thead>
              <tbody>
                {data.agent_workload.map((row) => (
                  <tr key={row.agent} className="border-t border-slate-200">
                    <td className="py-1">{row.agent}</td>
                    <td className="py-1 font-mono">{row.locked}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="mt-2 text-sm text-slate-500">No tickets are currently held by an agent.</p>
          )}
        </div>
      </div>

      <div className="card p-4">
        <h2 className="text-sm font-semibold">SLA breach risk</h2>
        {data.sla_at_risk.length ? (
          <table className="mt-3 w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th scope="col" className="py-1">Ticket</th>
                <th scope="col" className="py-1">Department</th>
                <th scope="col" className="py-1">Band</th>
                <th scope="col" className="py-1">Time remaining</th>
              </tr>
            </thead>
            <tbody>
              {data.sla_at_risk.map((row) => (
                <tr key={row.ticket_id} className="border-t border-slate-200">
                  <td className="py-1">
                    <Link className="font-mono text-xs text-blue-800 underline" to={`/tickets/${row.ticket_id}`}>
                      {row.ticket_id.slice(0, 10)}…
                    </Link>
                  </td>
                  <td className="py-1">{row.department}</td>
                  <td className="py-1">{row.priority_band ?? ","}</td>
                  <td className={`py-1 font-mono ${row.breached ? "font-semibold text-critical" : ""}`}>
                    {row.breached ? `overdue ${Math.abs(row.minutes_left).toFixed(0)}m` : `${row.minutes_left.toFixed(0)}m`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No ticket is within two hours of its SLA target.</p>
        )}
      </div>

      <div className="card p-4">
        <h2 className="text-sm font-semibold">AI outcome breakdown</h2>
        <dl className="mt-3 grid gap-4 sm:grid-cols-5">
          <Stat compact label="Approved unedited" value={outcomes.approved_unedited} />
          <Stat compact label="Approved after edit" value={outcomes.approved_edited} />
          <Stat compact label="Rejected" value={outcomes.rejected} />
          <Stat compact label="Rejection rate" value={percent(outcomes.rejection_rate)} />
          <Stat compact label="Reviewed" value={outcomes.reviewed} />
        </dl>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  compact,
}: {
  label: string;
  value: string | number;
  hint?: string;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "" : "card p-4"}>
      <dt className="label">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
      {hint ? <p className="text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}

function percent(value: number | null): string {
  return value === null || value === undefined ? "," : `${Math.round(value * 100)}%`;
}
