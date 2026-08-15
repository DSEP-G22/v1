# delivery_gateway

Implements REQ-BR-1 and REQ-SAFE-1: the only egress path out of the system. `send()` raises
`DeliveryRefused` if no `approval_id` (an `agent_decision.id`) is supplied, matching the
`delivery.approval_id` NOT NULL FK, and is the only package permitted to import
`MailGatewayPort` (enforced by `tests/architecture/test_imports.py`). Called by `workspace_api`
after it records the approving `agent_decision`. Owns `delivery`.
