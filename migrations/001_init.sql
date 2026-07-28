-- Generated from libs/platform/db/models.py via scripts/generate_migration.py
-- Forward-only. Do not hand-edit; add 002_*.sql for further changes.

CREATE TABLE action_registry_entry (
	id VARCHAR NOT NULL, 
	action_id VARCHAR NOT NULL, 
	department VARCHAR NOT NULL, 
	description TEXT NOT NULL, 
	mapped_faults JSON NOT NULL, 
	requires_supervisor BOOLEAN NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	requires_fields JSON NOT NULL, 
	impact_limits JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (action_id)
);

CREATE TABLE dlq_entry (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	original_topic VARCHAR NOT NULL, 
	original_group VARCHAR NOT NULL, 
	error TEXT NOT NULL, 
	attempts INTEGER NOT NULL, 
	body JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	replayed_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE TABLE organization (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE outbox (
	id VARCHAR NOT NULL, 
	topic VARCHAR NOT NULL, 
	"key" VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	published_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE TABLE app_user (
	id VARCHAR NOT NULL, 
	org_id VARCHAR NOT NULL, 
	username VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	email VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(org_id) REFERENCES organization (id), 
	UNIQUE (username)
);

CREATE TABLE customer (
	id VARCHAR NOT NULL, 
	org_id VARCHAR NOT NULL, 
	external_ref VARCHAR, 
	name VARCHAR NOT NULL, 
	email VARCHAR, 
	segment VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(org_id) REFERENCES organization (id)
);

CREATE TABLE knowledge_document (
	id VARCHAR NOT NULL, 
	org_id VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	source_path VARCHAR NOT NULL, 
	doc_type VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(org_id) REFERENCES organization (id)
);

CREATE TABLE config_version (
	id VARCHAR NOT NULL, 
	entity_type VARCHAR NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	data JSON NOT NULL, 
	changed_by VARCHAR, 
	changed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(changed_by) REFERENCES app_user (id)
);

CREATE TABLE knowledge_chunk (
	id VARCHAR NOT NULL, 
	document_id VARCHAR NOT NULL, 
	chunk_index INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	embedding_model VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES knowledge_document (id)
);

CREATE TABLE ticket (
	id VARCHAR NOT NULL, 
	org_id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	channel VARCHAR NOT NULL, 
	state VARCHAR NOT NULL, 
	department VARCHAR, 
	priority_score INTEGER, 
	priority_band VARCHAR, 
	idempotency_key VARCHAR, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_ticket_priority_score CHECK (priority_score IS NULL OR priority_score BETWEEN 0 AND 100), 
	FOREIGN KEY(org_id) REFERENCES organization (id), 
	FOREIGN KEY(customer_id) REFERENCES customer (id)
);

CREATE TABLE action_execution (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	action_id VARCHAR NOT NULL, 
	parameters_hash VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	external_ref VARCHAR, 
	idempotency_key VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ux_action_execution_idem UNIQUE (ticket_id, action_id, parameters_hash), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE action_recommendation (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	action_id VARCHAR NOT NULL, 
	parameters JSON NOT NULL, 
	requires_supervisor BOOLEAN NOT NULL, 
	status VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE agent_decision (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	type VARCHAR NOT NULL, 
	actor_id VARCHAR NOT NULL, 
	at DATETIME NOT NULL, 
	reason_code VARCHAR, 
	"before" TEXT, 
	"after" TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id), 
	FOREIGN KEY(actor_id) REFERENCES app_user (id)
);

CREATE TABLE aggregation_received_item (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	item VARCHAR NOT NULL, 
	received_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ux_aggregation_received_item UNIQUE (ticket_id, item), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE aggregation_state (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	expected_set JSON NOT NULL, 
	window_expires_at DATETIME NOT NULL, 
	status VARCHAR NOT NULL, 
	original_text TEXT NOT NULL, 
	text_flags JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (ticket_id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE attachment (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	modality VARCHAR NOT NULL, 
	object_key VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	original_filename VARCHAR NOT NULL, 
	content_type VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE audit_record (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR, 
	actor_id VARCHAR, 
	action VARCHAR NOT NULL, 
	detail JSON NOT NULL, 
	at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id), 
	FOREIGN KEY(actor_id) REFERENCES app_user (id)
);

CREATE TABLE diagnosis (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	intent VARCHAR NOT NULL, 
	fault VARCHAR, 
	confidence FLOAT NOT NULL, 
	alternatives JSON NOT NULL, 
	rationale TEXT NOT NULL, 
	needs_human_diagnosis BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE draft_response (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	ai_text TEXT NOT NULL, 
	current_text TEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	findings JSON NOT NULL, 
	ai_generated BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE queue_projection (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	department VARCHAR, 
	priority_band VARCHAR, 
	state VARCHAR NOT NULL, 
	customer_name VARCHAR NOT NULL,
	locked_by VARCHAR,
	updated_at DATETIME NOT NULL,
	channel VARCHAR,
	priority_score INTEGER,
	department_confidence FLOAT,
	fault VARCHAR,
	diagnosis_confidence FLOAT,
	modalities JSON,
	flags JSON,
	ticket_created_at DATETIME,
	sla_due_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (ticket_id),
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE INDEX ix_queue_projection_order ON queue_projection (department, priority_band, priority_score DESC, ticket_created_at);

CREATE TABLE ticket_state_transition (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	from_state VARCHAR NOT NULL, 
	to_state VARCHAR NOT NULL, 
	at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE triage_result (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	department VARCHAR NOT NULL, 
	department_confidence FLOAT NOT NULL, 
	alternatives JSON NOT NULL, 
	sentiment VARCHAR NOT NULL, 
	signals JSON NOT NULL, 
	priority_score INTEGER NOT NULL, 
	band VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE unified_payload (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	revision INTEGER NOT NULL, 
	schema_version VARCHAR NOT NULL, 
	original_text TEXT NOT NULL, 
	fused_text TEXT NOT NULL, 
	provenance JSON NOT NULL, 
	flags JSON NOT NULL, 
	partial BOOLEAN NOT NULL, 
	metadata JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ux_unified_payload_ticket_revision UNIQUE (ticket_id, revision), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id)
);

CREATE TABLE audio_transcript (
	id VARCHAR NOT NULL, 
	attachment_id VARCHAR NOT NULL, 
	text TEXT NOT NULL, 
	segments JSON NOT NULL, 
	language VARCHAR NOT NULL, 
	duration_s FLOAT NOT NULL, 
	acoustic_sentiment VARCHAR NOT NULL, 
	confidence FLOAT NOT NULL, 
	low_confidence BOOLEAN NOT NULL, 
	model_version VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ux_audio_transcript_att_model UNIQUE (attachment_id, model_version), 
	FOREIGN KEY(attachment_id) REFERENCES attachment (id)
);

CREATE TABLE citation (
	id VARCHAR NOT NULL, 
	diagnosis_id VARCHAR NOT NULL, 
	chunk_id VARCHAR NOT NULL, 
	chunk_version INTEGER NOT NULL, 
	relevance FLOAT NOT NULL, 
	verified BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(diagnosis_id) REFERENCES diagnosis (id)
);

CREATE TABLE delivery (
	id VARCHAR NOT NULL, 
	ticket_id VARCHAR NOT NULL, 
	draft_response_id VARCHAR NOT NULL, 
	approval_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	channel VARCHAR NOT NULL, 
	to_address VARCHAR NOT NULL, 
	sent_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ticket_id) REFERENCES ticket (id), 
	FOREIGN KEY(draft_response_id) REFERENCES draft_response (id), 
	FOREIGN KEY(approval_id) REFERENCES agent_decision (id)
);

CREATE TABLE visual_summary (
	id VARCHAR NOT NULL, 
	attachment_id VARCHAR NOT NULL, 
	prompt_template VARCHAR NOT NULL, 
	summary_text TEXT NOT NULL, 
	extracted_fields JSON NOT NULL, 
	confidence FLOAT NOT NULL, 
	low_confidence BOOLEAN NOT NULL, 
	model_version VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ux_visual_summary_att_model UNIQUE (attachment_id, model_version), 
	FOREIGN KEY(attachment_id) REFERENCES attachment (id)
);
