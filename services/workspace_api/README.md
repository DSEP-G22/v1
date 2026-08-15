# workspace_api

Implements REQ-WKS-1..18: the human-agent front door. `GET /queue` and `GET /tickets/{id}` read
from `queue_projection`/the analysis tables; `POST /tickets/{id}/lock`, `PATCH .../draft`,
`POST .../approve` (writes `agent_decision` then calls `delivery_gateway`), `POST .../reject`,
and `POST .../actions/{rec_id}/execute` (calls `action_svc`) mutate state. `WS /ws/queue` pushes
the current queue snapshot on demand. Auth is a static bearer token per role from `.env`
(`libs/platform/auth.py`, shared with `admin_api`), enough to exercise authorization checks
without an IdP.
Owns `agent_decision` and the lock/state-transition paths of `ticket`/`queue_projection` and the
edit path of `draft_response.current_text`. The only documented exception to "no service imports
another service" (see `tests/architecture/test_imports.py`): it calls `action_svc` and
`delivery_gateway` synchronously and `projector_svc.sync_state` to keep the queue projection
current after a lock/approve/reject.
