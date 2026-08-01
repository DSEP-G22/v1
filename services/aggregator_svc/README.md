# aggregator_svc

Implements REQ-FUS-1..10, the fusion statechart of SAD §6.5: consumes `tickets.text.done`,
`tickets.audio.done`, `tickets.image.done`, records each idempotently against
`aggregation_state`, and finalises the ticket the moment the completion set is satisfied (success
or failure both count as "received" — a failed attachment never blocks completion, it just marks
the payload `partial`). A single background sweeper thread finalises any window that expires
before completion. Uses `policy.fusion.fuse`, validates the result, and writes `unified_payload`
revision *n+1*. Owns `unified_payload` and updates `aggregation_state`.
