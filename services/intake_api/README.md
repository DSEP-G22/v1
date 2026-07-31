# intake_api

Implements REQ-ING-1..15: accepts a new support ticket (`POST /api/v1/tickets`, multipart text +
files + customer_id + channel + `Idempotency-Key`), validates attached media by sniffing magic
bytes rather than trusting the declared MIME type, stores media via `ObjectStorePort`, and writes
`ticket` + `attachment` + an outbox row for `tickets.raw` in a single transaction. It owns the
`ticket` and `attachment` tables (create path) and exposes `GET /api/v1/tickets/{id}/status`.
