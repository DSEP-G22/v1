# action_svc

Re-validates an `action_recommendation` against the *current* `action_registry_entry` (the
registry may have changed since `response_svc` proposed it) and executes it idempotently, keyed
by `(ticket_id, action_id, sha256(params))` via the unique constraint on `action_execution`. Only
this package may import `ActionAdapterPort` (enforced by `tests/architecture/test_imports.py`).
Called by `workspace_api`'s `POST /tickets/{id}/actions/{rec_id}/execute`. Owns `action_execution`
and the status-update path of `action_recommendation`.
