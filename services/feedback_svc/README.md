# feedback_svc

Converts human decisions into labelled training examples, which is what allows the models to
improve as agents use the system.

- **Implements:** the continuous-learning loop (no SRS requirement; an addition beyond v1 scope)
- **Called by:** `workspace_api` after every decision is persisted
- **Owns (writes):** `training_example`
- **Reads:** `agent_decision`, `unified_payload`, `triage_result`, `diagnosis`

Not a broker consumer. Harvesting runs in the same request that records the decision, so a
label can never be lost to a dropped event, and it is idempotent on `(decision_id, task)` so a
retry cannot duplicate one.

See `docs/15-continuous-learning.md` for which decision types yield which labels and why.
