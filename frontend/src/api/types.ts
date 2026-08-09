// Mirrors the JSON returned by services/workspace_api and services/admin_api. Kept hand-written
// rather than generated so the shapes the UI depends on are reviewable in one place; if a field
// here stops matching the API, the contract test in tests/contract is the place to catch it.

export type PriorityBand = "critical" | "high" | "normal" | "low";

export interface QueueRow {
  ticket_id: string;
  department: string | null;
  priority_band: PriorityBand | null;
  priority_score: number | null;
  department_confidence: number | null;
  fault: string | null;
  diagnosis_confidence: number | null;
  state: string;
  channel: string | null;
  customer_name: string;
  locked_by: string | null;
  modalities: string[];
  flags: string[];
  created_at: string | null;
  sla_due_at: string | null;
  updated_at: string | null;
}

export interface TranscriptSegment {
  start_s: number;
  end_s: number;
  text: string;
  confidence: number;
}

export interface Transcript {
  text: string;
  segments: TranscriptSegment[];
  language: string;
  duration_s: number;
  acoustic_sentiment: string;
  confidence: number;
  low_confidence: boolean;
  model_version: string;
}

export interface VisualSummary {
  prompt_template: string;
  summary_text: string;
  extracted_fields: Record<string, unknown>;
  confidence: number;
  low_confidence: boolean;
  model_version: string;
}

export interface Attachment {
  id: string;
  modality: string;
  status: string;
  original_filename: string;
  content_type: string;
  content_url: string;
  transcript: Transcript | null;
  visual_summary: VisualSummary | null;
}

export interface ProvenanceEntry {
  modality: string;
  source: string;
  span: [number, number];
  confidence: number;
  model_version?: string | null;
}

export interface Citation {
  chunk_id: string;
  chunk_version: number;
  relevance: number;
  verified: boolean;
  excerpt: string | null;
}

export interface TicketDetail {
  ticket_id: string;
  state: string;
  channel: string | null;
  created_at: string | null;
  updated_at: string | null;
  department: string | null;
  priority_band: PriorityBand | null;
  priority_score: number | null;
  customer: { id: string; name: string; email: string | null; segment: string } | null;
  attachments: Attachment[];
  payload: {
    original_text: string;
    fused_text: string;
    provenance: ProvenanceEntry[];
    partial: boolean;
    flags: string[];
    revision: number;
    schema_version: string;
  } | null;
  triage: {
    department: string;
    department_confidence: number;
    alternatives: unknown[];
    sentiment: string;
    signals: { name?: string; label?: string; weight?: number; value?: unknown }[];
    priority_score: number;
    band: PriorityBand;
  } | null;
  diagnosis: {
    id: string;
    intent: string;
    fault: string | null;
    confidence: number;
    alternatives: unknown[];
    rationale: string;
    needs_human_diagnosis: boolean;
    citations: Citation[];
  } | null;
  draft: {
    id: string;
    ai_text: string;
    current_text: string;
    revision: number;
    findings: { code?: string; message?: string; severity?: string }[];
    ai_generated: boolean;
  } | null;
  recommendations: {
    id: string;
    action_id: string;
    parameters: Record<string, unknown>;
    requires_supervisor: boolean;
    status: string;
  }[];
  decisions: { id: string; type: string; actor_id: string; at: string | null; reason_code: string | null }[];
}

export interface DashboardMetrics {
  generated_at: string;
  queue_depth_by_department: { department: string; open: number; total: number }[];
  queue_depth_by_band: Record<string, number>;
  ageing: { lt_1h: number; h1_4: number; h4_24: number; gt_24h: number };
  sla_at_risk: {
    ticket_id: string;
    department: string;
    priority_band: string | null;
    minutes_left: number;
    breached: boolean;
  }[];
  agent_workload: { agent: string; locked: number }[];
  ai_outcomes: {
    reviewed: number;
    approved: number;
    approved_unedited: number;
    approved_edited: number;
    rejected: number;
    acceptance_rate: number | null;
    edit_rate: number | null;
    rejection_rate: number | null;
  };
}

export interface CurrentUser {
  user_id: string;
  username: string;
  role: "agent" | "lead" | "admin";
}

export interface ActionRegistryEntry {
  action_id: string;
  department: string;
  description: string;
  mapped_faults: string[];
  requires_supervisor: boolean;
  enabled: boolean;
  requires_fields: string[];
  impact_limits: Record<string, number>;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  doc_type: string;
  source_path: string;
  created_at: string;
  chunk_count: number;
}

export interface KnowledgeHit {
  chunk_id: string | null;
  score: number;
  text: string;
  metadata: Record<string, unknown>;
}

export interface DlqEntry {
  id: string;
  ticket_id: string;
  original_topic: string;
  original_group: string;
  error: string;
  attempts: number;
  created_at: string;
}
