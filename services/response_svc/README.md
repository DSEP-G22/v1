# response_svc

Implements REQ-RES-1..12: consumes `tickets.diagnosed`, drafts a reply with
`models/prompts/llm/draft.txt` (constrained to cite only retrieved procedures, no compensation
promises), runs `policy.compliance.check`, and selects an action recommendation via
`policy.action_selection` against the `action_registry` table. Writes `draft_response` +
`action_recommendation`, transitions the ticket to `READY_FOR_AGENT`, and publishes
`tickets.ready`. Owns `draft_response` and the create path of `action_recommendation`.
