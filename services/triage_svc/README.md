# triage_svc

Implements REQ-CLS-* and REQ-PRI-*: consumes `tickets.aggregated`, classifies the fused text via
`ClassifierPort`, applies `config/routing_rules.yaml` through `policy.routing.evaluate` (first
matching rule overrides the classifier), scores priority via `policy.priority.score`, writes
`triage_result`, updates the `ticket` row's department/priority summary, and publishes
`tickets.triaged`. Owns `triage_result`.
