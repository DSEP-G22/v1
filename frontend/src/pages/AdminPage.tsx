import { useState } from "react";

import { useActionRegistry, useDlq, useModels, useReplayDlq, useRoutingRules, useThresholds, useUsers } from "../api/hooks";
import { ErrorPanel } from "../components/ErrorPanel";
import { useToasts } from "../components/Toasts";

// UI-5. User and role management, the routing-rule and threshold view, model version selection,
// and the pipeline health / dead-letter viewer.
//
// Thresholds and routing rules are read-only here: the admin API writes routing rules to a YAML
// file that is loaded at start-up, and hot-reloading configuration into running consumers is not
// implemented in v1 (see docs/09-operations.md). Showing them read-only is honest; offering an
// editor that silently required a restart would not be.

type Tab = "users" | "routing" | "thresholds" | "models" | "actions" | "dlq";

const TABS: { id: Tab; label: string }[] = [
  { id: "users", label: "Users" },
  { id: "routing", label: "Routing rules" },
  { id: "thresholds", label: "Thresholds" },
  { id: "models", label: "Models" },
  { id: "actions", label: "Action registry" },
  { id: "dlq", label: "Dead-letter queue" },
];

export function AdminPage() {
  const [tab, setTab] = useState<Tab>("users");

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Administration</h1>

      <div role="tablist" aria-label="Administration sections" className="flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((item) => (
          <button
            key={item.id}
            role="tab"
            id={`tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`panel-${item.id}`}
            className={`rounded-t px-3 py-2 text-sm ${
              tab === item.id ? "border-b-2 border-blue-700 font-semibold text-blue-800" : "text-slate-600 hover:bg-slate-100"
            }`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "users" ? <UsersPanel /> : null}
        {tab === "routing" ? <RoutingPanel /> : null}
        {tab === "thresholds" ? <ThresholdsPanel /> : null}
        {tab === "models" ? <ModelsPanel /> : null}
        {tab === "actions" ? <ActionRegistryPanel /> : null}
        {tab === "dlq" ? <DlqPanel /> : null}
      </div>
    </div>
  );
}

function UsersPanel() {
  const { data, error, refetch, isLoading } = useUsers();
  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load users" />;
  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <div className="card overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
          <tr>
            <th scope="col" className="px-3 py-2">Username</th>
            <th scope="col" className="px-3 py-2">Role</th>
            <th scope="col" className="px-3 py-2">Email</th>
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((user) => (
            <tr key={user.id} className="border-t border-slate-200">
              <td className="px-3 py-2">{user.username}</td>
              <td className="px-3 py-2">{user.role}</td>
              <td className="px-3 py-2 text-slate-600">{user.email ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RoutingPanel() {
  const { data, error, refetch } = useRoutingRules();
  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load routing rules" />;
  return (
    <div className="card p-4">
      <p className="text-xs text-slate-500">
        Read-only in v1 — rules are stored in <code className="font-mono">config/routing_rules.yaml</code> and applied at
        service start-up.
      </p>
      <pre className="mt-3 max-h-96 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
        {JSON.stringify(data ?? [], null, 2)}
      </pre>
    </div>
  );
}

function ThresholdsPanel() {
  const { data, error, refetch } = useThresholds();
  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load thresholds" />;
  return (
    <div className="card p-4">
      <p className="text-xs text-slate-500">
        Read-only in v1 — change these in <code className="font-mono">.env</code> and restart the process.
      </p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        {Object.entries(data ?? {}).map(([key, value]) => (
          <div key={key} className="rounded border border-slate-200 px-3 py-2">
            <dt className="label">{key.replace(/_/g, " ")}</dt>
            <dd className="mt-1 font-mono text-sm">{String(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ModelsPanel() {
  const { data, error, refetch } = useModels();
  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load model registry" />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="card p-4">
        <h2 className="text-sm font-semibold">Active in this process</h2>
        <dl className="mt-3 space-y-2 text-sm">
          {Object.entries(data?.active ?? {}).map(([key, value]) => (
            <div key={key} className="flex justify-between gap-3 border-b border-slate-100 pb-1">
              <dt className="text-slate-500">{key.replace(/_/g, " ")}</dt>
              <dd className="font-mono">{String(value)}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="card p-4">
        <h2 className="text-sm font-semibold">Declared in config/registry.yaml</h2>
        <pre className="mt-3 max-h-80 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
          {JSON.stringify(data?.declared ?? {}, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function ActionRegistryPanel() {
  const { data, error, refetch } = useActionRegistry();
  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load the action registry" />;
  return (
    <div className="card overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
          <tr>
            <th scope="col" className="px-3 py-2">Action</th>
            <th scope="col" className="px-3 py-2">Department</th>
            <th scope="col" className="px-3 py-2">Mapped faults</th>
            <th scope="col" className="px-3 py-2">Supervisor</th>
            <th scope="col" className="px-3 py-2">Enabled</th>
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((entry) => (
            <tr key={entry.action_id} className="border-t border-slate-200 align-top">
              <td className="px-3 py-2">
                <span className="font-mono text-xs">{entry.action_id}</span>
                <p className="text-xs text-slate-500">{entry.description}</p>
              </td>
              <td className="px-3 py-2">{entry.department}</td>
              <td className="px-3 py-2 text-xs">{entry.mapped_faults.join(", ") || "—"}</td>
              <td className="px-3 py-2">{entry.requires_supervisor ? "Required" : "No"}</td>
              <td className="px-3 py-2">{entry.enabled ? "Yes" : "Disabled"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DlqPanel() {
  const toasts = useToasts();
  const { data, error, refetch, isLoading } = useDlq();
  const replay = useReplayDlq();

  if (error) return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load the dead-letter queue" />;
  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!data?.length) return <p className="card p-4 text-sm text-slate-600">The dead-letter queue is empty.</p>;

  return (
    <div className="card overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
          <tr>
            <th scope="col" className="px-3 py-2">Ticket</th>
            <th scope="col" className="px-3 py-2">Topic</th>
            <th scope="col" className="px-3 py-2">Error</th>
            <th scope="col" className="px-3 py-2">Attempts</th>
            <th scope="col" className="px-3 py-2">Action</th>
          </tr>
        </thead>
        <tbody>
          {data.map((entry) => (
            <tr key={entry.id} className="border-t border-slate-200 align-top">
              <td className="px-3 py-2 font-mono text-xs">{entry.ticket_id.slice(0, 10)}…</td>
              <td className="px-3 py-2 font-mono text-xs">{entry.original_topic}</td>
              <td className="px-3 py-2 max-w-md text-xs text-red-900">{entry.error}</td>
              <td className="px-3 py-2 font-mono text-xs">{entry.attempts}</td>
              <td className="px-3 py-2">
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={replay.isPending}
                  onClick={async () => {
                    try {
                      await replay.mutateAsync(entry.id);
                      toasts.push("Message replayed onto its original topic.", "success");
                    } catch {
                      toasts.push("The replay failed.", "error");
                    }
                  }}
                >
                  Replay
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
