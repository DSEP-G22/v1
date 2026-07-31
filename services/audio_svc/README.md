# audio_svc

Implements REQ-ASR-1..12: consumes `tickets.audio.work`, retries `TranscriberPort.transcribe`
twice, writes the `audio_transcript` row (idempotent upsert on `(attachment_id, model_version)`),
and publishes `tickets.audio.done`. On terminal failure it still publishes `tickets.audio.done`
with `status=failed` and marks the attachment `FAILED` — never silently drops it, or the
aggregation window would never close early. Owns the `audio_transcript` table.
