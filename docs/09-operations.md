# 09, Operations

## Run modes

| Mode | Command | What runs |
|---|---|---|
| Single-process demo | `python -m runtime.local` | `intake_api` + all 11 broker consumers + `workspace_api` (mounted `/workspace`) + `admin_api` (mounted `/admin`) on one Uvicorn process, port 8000; outbox drainer + aggregation sweeper as background threads. Serves no UI. |
| Agent workspace UI | `cd frontend && npm run dev` | Separate process on port 5300, proxying the API to :8000. Production: `npm run build` with `VITE_API_BASE` set, then serve `dist/` from any static host. See [14-ui.md](14-ui.md). |
| Demo ticket | `python -m runtime.demo_ticket` | Posts one text+audio+image ticket, polls to `READY_FOR_AGENT`, prints payload/triage/diagnosis/draft |
| Standalone service | `python -m services.<name>` | Any single service against the configured `DATABASE_URL`/`BROKER`, e.g. `python -m services.audio_svc` (works for the 13 services that have a `__main__.py`: `intake_api, routing_svc, text_svc, audio_svc, image_svc, aggregator_svc, triage_svc, orchestrator_svc, response_svc, projector_svc, workspace_api, admin_api`). `retrieval_svc` is a library (no `__main__.py`); `delivery_gateway` and `action_svc` are called synchronously by `workspace_api`, not standalone processes. |
| Multi-process (`full` profile) | run each `services.*` standalone against `BROKER=kafka` and a shared Postgres `DATABASE_URL` | Closer to the SAD's target deployment; every service still goes through the same ports, so no service code changes |

## Health checks

- `GET /admin/health` -> `{"status": "ok"}` (no auth required)
- `GET /api/v1/tickets/{id}/status` (intake_api, mounted at `/`), ticket state, department,
  priority; useful as a liveness probe for the full pipeline (create a throwaway ticket, poll its
  status)
- Ollama: `curl http://localhost:11434/api/tags`, must return without error before `cpu`/`full`
  profile services will produce real (non-error-fallback) diagnoses/drafts

## DLQ listing and replay

Every event that exhausts `max_retries` (default 3) in `InProcessBroker`/`KafkaBroker` is
produced to `tickets.dlq`; `libs/platform/dlq.py::install_dlq_capture` (wired by
`runtime/wiring.py`) durably persists it to the `dlq_entry` table, the DLQ topic itself has no
persistence, so this capture step is required or DLQ events simply vanish once the in-memory
queue is drained.

```
curl -H "Authorization: Bearer dev-admin-token" http://localhost:8000/admin/dlq
curl -X POST -H "Authorization: Bearer dev-admin-token" http://localhost:8000/admin/dlq/{entry_id}/replay
```

Replay re-produces the original envelope to its original topic (stored in
`dlq_entry.body.original_envelope`/`original_topic`) and marks the entry `replayed_at`, it does
not retry in place, so a still-broken handler will just DLQ it again with a new entry.

## Common failures (see also `11-troubleshooting.md` for the full symptom table)

- **Ticket stuck at `PROCESSING`**: check `aggregation_state` for the ticket, the sweeper thread
  (`services/aggregator_svc/handler.py::sweep`, called every 5s by `runtime/wiring.py`) should
  close any window past `window_expires_at` as `partial=True`. If it's still open past the
  window, the sweeper thread may have died, check for an uncaught exception in its log lines.
- **`sqlite3.OperationalError: database is locked`**: confirm WAL mode is active
  (`PRAGMA journal_mode` should read `wal`; `libs/platform/db/session.py::build_engine` sets this
  automatically for `sqlite://` URLs) and that no code path holds a `Session` open across a
  broker-thread boundary, one session per handler invocation, always via `session_scope`.
- **Duplicate rows after a broker retry**: every writer must be idempotent on its natural key,
  `audio_transcript`/`visual_summary` upsert on `(attachment_id, model_version)`,
  `unified_payload` on `(ticket_id, revision)`, `action_execution` on
  `(ticket_id, action_id, parameters_hash)`, `aggregation_received_item` on `(ticket_id, item)`.
  If a new writer doesn't have a matching unique constraint, it isn't safe under at-least-once
  delivery.

## Log reference

JSON structured logs (`libs/observability/logging.py`) with fields `level, logger, message,
time`, plus `ticket_id, stage, duration_ms, model_version` when set via
`log_stage()`/`extra={...}`. `configure_logging()` installs a single `StreamHandler` to stdout,
call it once at process start (`runtime/local.py` and each service's `__main__.py` should call it
before building ports; note: not currently wired automatically into every `__main__.py`, add
`from libs.observability.logging import configure_logging; configure_logging()` at the top of
`main()` if a standalone service's logs aren't appearing).

## Metric reference

`libs/observability/metrics.py::get_registry()`, in-process counters (`increment`) and
histograms (`observe`), labelled (`name{k=v,...}`). `@timed(stage)` decorator wraps a function and
records `{stage}_duration_ms`. `MetricsRegistry.to_prometheus_text()` renders a scrape-able text
format, no HTTP endpoint currently exposes it (wire one into `admin_api` if Prometheus scraping
is needed; the registry itself is process-global and ready to be read from anywhere in-process).
For actual stage-latency numbers, prefer `ticket_state_transition` (queried by
`evaluation/harness/metrics.py::StageLatencies`), it's free, already-persisted instrumentation
covering every ticket, not just what happens to be running when a scrape fires.
