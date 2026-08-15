"""Machine-readable single-writer ownership table (SAD §5.2.2), consumed by
tests/architecture/test_single_writer.py. Maps each repository's *mutating* methods to the one
or more `services/*` packages allowed to call them. Read methods (get*, list*, first) are
unrestricted, the ownership rule is about who may change a table, not who may read it.

Services not yet built (delivery_gateway, action_svc, workspace_api, admin_api, knowledge_ingest)
are still listed here so the rule is already correct once those packages exist."""

from __future__ import annotations

WRITE_METHOD_OWNERS: dict[str, dict[str, set[str]]] = {
    "TicketRepo": {
        "create": {"intake_api"},
        "update_state": {"intake_api", "aggregator_svc", "triage_svc", "orchestrator_svc", "response_svc", "workspace_api"},
        "update_triage_summary": {"triage_svc"},
    },
    "AttachmentRepo": {
        "create": {"intake_api"},
        "set_status": {"intake_api", "audio_svc", "image_svc"},
    },
    "AggregationStateRepo": {
        "create": {"routing_svc"},
        "set_text": {"aggregator_svc"},
        "set_status": {"aggregator_svc"},
    },
    "AggregationReceivedItemRepo": {
        "mark": {"aggregator_svc"},
    },
    "AudioTranscriptRepo": {
        "upsert": {"audio_svc"},
    },
    "VisualSummaryRepo": {
        "upsert": {"image_svc"},
    },
    "UnifiedPayloadRepo": {
        "create": {"aggregator_svc"},
    },
    "TriageResultRepo": {
        "create": {"triage_svc"},
    },
    "DiagnosisRepo": {
        "create": {"orchestrator_svc"},
    },
    "DraftResponseRepo": {
        "create": {"response_svc"},
        "update_current_text": {"workspace_api"},
    },
    "ActionRecommendationRepo": {
        "create": {"response_svc"},
        "set_status": {"action_svc", "workspace_api"},
    },
    "ActionExecutionRepo": {
        "create_if_absent": {"action_svc"},
        "set_status": {"action_svc"},
    },
    "AgentDecisionRepo": {
        "create": {"workspace_api"},
    },
    "DeliveryRepo": {
        "create": {"delivery_gateway"},
    },
    "QueueProjectionRepo": {
        "upsert": {"projector_svc"},
        "set_lock": {"workspace_api"},
    },
    "KnowledgeDocumentRepo": {
        "create": {"knowledge_ingest"},
    },
    "KnowledgeChunkRepo": {
        "create": {"knowledge_ingest"},
    },
    "ActionRegistryEntryRepo": {
        "upsert": {"admin_api"},
    },
    "AppUserRepo": {
        "create": {"admin_api"},
    },
    "ConfigVersionRepo": {
        "create": {"admin_api"},
    },
    "OrganizationRepo": {
        "create": {"admin_api"},
    },
    "CustomerRepo": {
        "create": {"admin_api"},
    },
    "DlqEntryRepo": {
        "mark_replayed": {"admin_api"},
    },
    # Append-only / shared, no single owner.
    "AuditRecordRepo": {},
}
