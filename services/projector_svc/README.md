# projector_svc

Maintains the `queue_projection` read model from `tickets.ready` and from workspace commands
(`sync_state`, called by `workspace_api` after lock/approve/reject). The workspace queue endpoint
reads only this projection, never the analysis tables, so triage/diagnosis schema changes
never touch the queue read path. Owns `queue_projection`.
