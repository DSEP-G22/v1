# image_svc

Implements REQ-VLM-1..12: consumes `tickets.image.work`, picks a prompt template via
`choose_template`, retries `VisualExtractorPort.extract` twice, writes the `visual_summary` row
(idempotent upsert on `(attachment_id, model_version)`), and publishes `tickets.image.done`. On
terminal failure it still publishes `tickets.image.done` with `status=failed`. Owns the
`visual_summary` table.
