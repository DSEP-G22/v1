# admin_api

Users, routing rules, action registry CRUD, health, and DLQ listing/replay. Every mutation writes
a `config_version` row (`create_user`, `upsert_action_registry_entry`, `put_routing_rules`).
Routing-rule edits rewrite `config/routing_rules.yaml` directly. `/thresholds` is read-only in
v1, hot-reloading `pydantic-settings` safely is out of scope; change a threshold via `.env` and
restart. `/dlq` and `/dlq/{id}/replay` read from and re-produce `dlq_entry` rows captured by
`libs/platform/dlq.py`. Owns `app_user`, `action_registry_entry`, `organization`, `customer`,
`config_version`, and the replay-marking path of `dlq_entry`.
