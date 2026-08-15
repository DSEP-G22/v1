import { useState } from "react";

import { useKnowledgeDocuments, useKnowledgeSearch, useUploadDocument } from "../api/hooks";
import { ErrorPanel } from "../components/ErrorPanel";
import { useToasts } from "../components/Toasts";

// UI-6. SOP upload with per-document ingestion status, and the knowledge-base search preview
// that runs the same dense query the retrieval service uses, so what is previewed here is what
// the pipeline will actually retrieve.
//
// Historical ticket import is not implemented in v1, the import path exists only as the
// evaluation dataset loader, so offering a button here would be a dead control.

export function OnboardingPage() {
  const toasts = useToasts();
  const { data: documents, error, refetch, isLoading } = useKnowledgeDocuments();
  const upload = useUploadDocument();

  const [file, setFile] = useState<File | null>(null);
  const [orgId, setOrgId] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const search = useKnowledgeSearch(query);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) {
      setFieldError("Choose a .md, .txt or .pdf document to upload.");
      return;
    }
    if (!orgId.trim()) {
      setFieldError("Enter the organization ID the document belongs to.");
      return;
    }
    setFieldError(null);
    try {
      const report = await upload.mutateAsync({ file, orgId: orgId.trim() });
      toasts.push(`Ingested "${report.title}" into ${report.num_chunks} chunks.`, "success");
      setFile(null);
    } catch {
      toasts.push("The document could not be ingested.", "error");
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Onboarding</h1>

      <div className="card p-4">
        <h2 className="text-sm font-semibold">Upload a standard operating procedure</h2>
        <form onSubmit={submit} className="mt-3 grid gap-4 md:grid-cols-3" noValidate>
          <div>
            <label className="label" htmlFor="org">
              Organization ID
            </label>
            <input id="org" className="input mt-1" value={orgId} onChange={(e) => setOrgId(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="doc">
              Document
            </label>
            <input
              id="doc"
              type="file"
              accept=".md,.txt,.pdf"
              className="input mt-1"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <div className="flex items-end">
            <button type="submit" className="btn-primary" disabled={upload.isPending}>
              {upload.isPending ? "Ingesting…" : "Upload and ingest"}
            </button>
          </div>
        </form>
        {fieldError ? (
          <p role="alert" className="mt-2 text-xs font-medium text-red-800">
            {fieldError}
          </p>
        ) : null}
        {upload.error ? <div className="mt-3"><ErrorPanel error={upload.error} title="Ingestion failed" /></div> : null}
      </div>

      <div className="card overflow-x-auto">
        <div className="card-header">
          <h2 className="text-sm font-semibold">Ingested documents</h2>
          <button type="button" className="btn-secondary" onClick={() => void refetch()}>
            Refresh
          </button>
        </div>
        {error ? (
          <div className="p-4">
            <ErrorPanel error={error} onRetry={() => void refetch()} title="Could not load documents" />
          </div>
        ) : isLoading ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
              <tr>
                <th scope="col" className="px-3 py-2">Title</th>
                <th scope="col" className="px-3 py-2">Type</th>
                <th scope="col" className="px-3 py-2">Chunks</th>
                <th scope="col" className="px-3 py-2">Status</th>
                <th scope="col" className="px-3 py-2">Ingested</th>
              </tr>
            </thead>
            <tbody>
              {(documents ?? []).map((doc) => (
                <tr key={doc.id} className="border-t border-slate-200">
                  <td className="px-3 py-2">{doc.title}</td>
                  <td className="px-3 py-2 font-mono text-xs">{doc.doc_type}</td>
                  <td className="px-3 py-2 font-mono text-xs">{doc.chunk_count}</td>
                  <td className="px-3 py-2">
                    {doc.chunk_count > 0 ? (
                      <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-green-900">
                        Indexed
                      </span>
                    ) : (
                      <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-900">
                        No chunks
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-500">{new Date(doc.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {!documents?.length ? (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                    No documents have been ingested yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        )}
      </div>

      <div className="card p-4">
        <h2 className="text-sm font-semibold">Knowledge base search preview</h2>
        <label className="label mt-3 block" htmlFor="kb-query">
          Query
        </label>
        <input
          id="kb-query"
          className="input mt-1"
          placeholder="e.g. router power light is red"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <p className="mt-1 text-xs text-slate-500">Type at least three characters. Results use the configured embedding model.</p>

        {search.error ? <div className="mt-3"><ErrorPanel error={search.error} title="Search failed" /></div> : null}

        <ul className="mt-3 space-y-2">
          {(search.data ?? []).map((hit, index) => (
            <li key={`${hit.chunk_id ?? index}`} className="rounded border border-slate-200 p-3">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span className="font-mono">{hit.chunk_id ?? ","}</span>
                <span className="font-mono">score {hit.score.toFixed(3)}</span>
              </div>
              <p className="mt-1 text-sm text-slate-800">{hit.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
