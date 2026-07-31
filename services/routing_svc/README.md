# routing_svc

Implements REQ-ING-8 and REQ-FUS-4: consumes `tickets.raw`, computes the expected per-modality
completion set (`{attachment_ids by modality} ∪ {"text"}`), opens the `aggregation_state` window,
and fans the ticket out to `tickets.audio.work`, `tickets.image.work`, and `tickets.text.work`. It
owns the `aggregation_state` table's create path.
