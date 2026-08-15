import { useLearning } from "../api/hooks";
import { ErrorPanel } from "./ErrorPanel";

// Continuous learning, surfaced for the administrator: how many human corrections are waiting to
// be trained on, what the model registry currently serves, and what previous retrains decided.
//
// Read-only by design. A retrain is a Spark job that takes minutes and can move the champion
// model, so it is launched deliberately from the command line or the DVC pipeline, not by a
// button in a web page that gives no feedback while it runs.

const RETRAIN_COMMANDS = [
  "# retrain with Spark, promoting only if the candidate wins",
  "python -m mlops.spark_retrain --task department --promote",
  "",
  "# or through the tracked pipeline",
  "dvc repro retrain",
].join("\n");

export function LearningPanel() {
  const { data, isLoading, error, refetch } = useLearning();

  if (error) {
    return <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load learning status" />;
  }
  if (isLoading || !data) {
    return <p className="p-4 text-sm text-slate-500">Loading...</p>;
  }

  const pending = data.pending_examples ?? {};
  const totalPending = Object.values(pending).reduce((a, b) => a + b, 0);
  const departmentPending = pending.department ?? 0;

  return (
    <div className="space-y-6 p-4">
      <section>
        <h2 className="text-sm font-semibold">Human labels awaiting training</h2>
        <p className="mt-1 text-xs text-slate-600">
          Every approval, reassignment and escalation is recorded as a labelled example. Approvals
          confirm the model was right; reassignments and escalations correct it, and are weighted
          more heavily when the model is retrained.
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          {Object.entries(pending).map(([task, count]) => (
            <div key={task} className="rounded border border-slate-200 p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">{task}</div>
              <div className="mt-1 text-2xl font-semibold">{count}</div>
            </div>
          ))}
        </div>

        <p className="mt-3 text-sm">
          {data.retrain_due ? (
            <span className="rounded bg-amber-100 px-2 py-1 font-medium text-amber-900">
              Retrain due: {departmentPending} of {data.retrain_threshold} department labels collected
            </span>
          ) : (
            <span className="text-slate-600">
              {totalPending} label(s) collected. Threshold for a retrain is {data.retrain_threshold}.
            </span>
          )}
        </p>

        <pre className="mt-3 overflow-auto rounded bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">
          {RETRAIN_COMMANDS}
        </pre>
      </section>

      <section>
        <h2 className="text-sm font-semibold">Model registry</h2>
        <p className="mt-1 text-xs text-slate-600">
          MLflow at <code className="font-mono">{data.registry.tracking_uri}</code>{" "}
          {data.registry.reachable ? (
            <span className="rounded bg-green-100 px-1.5 py-0.5 text-green-900">reachable</span>
          ) : (
            <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-900">
              unreachable, serving local artefacts
            </span>
          )}
        </p>

        <div className="mt-2 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Champion</th>
                <th className="px-3 py-2">Metrics</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.registry.models ?? {}).map(([role, model]) => (
                <tr key={role} className="border-t border-slate-200">
                  <td className="px-3 py-2 font-mono text-xs">{role}</td>
                  <td className="px-3 py-2 text-xs">
                    {model.version ? (
                      <>
                        v{model.version}
                        {model.run_id ? (
                          <span className="ml-2 font-mono text-slate-500">{model.run_id.slice(0, 8)}</span>
                        ) : null}
                      </>
                    ) : (
                      <span className="text-slate-400">{model.error ?? "not registered"}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {model.metrics
                      ? Object.entries(model.metrics)
                          .map(([key, value]) => key + "=" + (typeof value === "number" ? value.toFixed(3) : value))
                          .join("  ")
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold">Retraining history</h2>
        <p className="mt-1 text-xs text-slate-600">
          Spark master <code className="font-mono">{data.spark_master}</code>. A candidate replaces
          the champion only when it beats the incumbent on the held-out split, so a retrain can
          never make the deployed model worse.
        </p>

        {data.recent_runs.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">No retraining runs yet.</p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-3 py-2">Started</th>
                  <th className="px-3 py-2">Task</th>
                  <th className="px-3 py-2">Trigger</th>
                  <th className="px-3 py-2">New labels</th>
                  <th className="px-3 py-2">Baseline</th>
                  <th className="px-3 py-2">Candidate</th>
                  <th className="px-3 py-2">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_runs.map((run) => (
                  <tr key={run.id} className="border-t border-slate-200">
                    <td className="px-3 py-2 text-xs">{new Date(run.started_at).toLocaleString()}</td>
                    <td className="px-3 py-2 text-xs">{run.task}</td>
                    <td className="px-3 py-2 text-xs">{run.trigger}</td>
                    <td className="px-3 py-2 text-xs">{run.examples_new}</td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {run.baseline_metric !== null ? run.baseline_metric.toFixed(4) : "-"}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {run.candidate_metric !== null ? run.candidate_metric.toFixed(4) : "-"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <StatusChip status={run.status} promoted={run.promoted} />
                      {run.notes ? <div className="mt-1 text-slate-500">{run.notes.slice(0, 80)}</div> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StatusChip({ status, promoted }: { status: string; promoted: boolean }) {
  const tone =
    status === "SUCCEEDED"
      ? promoted
        ? "bg-green-100 text-green-900"
        : "bg-slate-100 text-slate-700"
      : status === "FAILED"
        ? "bg-red-100 text-red-900"
        : "bg-blue-100 text-blue-900";
  return (
    <span className={"rounded px-1.5 py-0.5 " + tone}>
      {status}
      {promoted ? ", promoted" : ""}
    </span>
  );
}
