export interface Folder {
  id: string;
  name: string;
  is_system: boolean;
}

export interface Paper {
  id: string;
  title: string;
  authors: string;
  year: string;
  language: string;
  file_name: string;
  parse_status: string;
  vector_status: string;
  note_status: string;
  obsidian_note_path: string;
  latest_note?: {
    id: string;
    obsidian_path: string;
    created_at: string;
    updated_at: string;
  } | null;
  metadata_warning: string;
  parse_warning: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  content?: string;
  execution?: ExecutionPayload;
  task_id?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  display_title?: string;
  task_count?: number;
  has_messages?: boolean;
  created_at: string;
  updated_at: string;
}

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface HarnessExecution {
  task_id?: string;
  run_id?: string;
  session_id?: string;
  runtime_status?: string;
  task_type?: string;
  chat_scope?: string;
  current_paper_id?: string;
  context_pack_strategy?: string;
  policy_checks?: JsonValue[];
  tool_summary?: ToolSummary;
  redaction?: {
    enabled?: boolean;
    redacted_fields?: string[];
  };
  fallbacks?: JsonValue[];
  latency_ms?: number;
}

export interface ToolSummary {
  total_calls?: number;
  failed_calls?: number;
  mcp_servers?: string[];
  calls_by_server?: Record<string, number>;
  total_latency_ms?: number;
}

export interface GraphStateSummary {
  task_type?: string;
  initial_phase?: string;
  standard_flow?: JsonValue[];
  node_visit_limit_ok?: boolean;
  node_visit_limit_error?: string;
}

export interface RetrievalSummary {
  retrieval_mode?: string;
  legacy_mode?: string;
  backend?: string;
  backend_diagnostics?: JsonObject;
  backend_status?: JsonObject;
  backend_config?: JsonObject;
  fallback_reason?: string;
  evidence_stats?: JsonObject;
  fallback?: boolean;
  query_analysis?: JsonObject;
  abstract_control?: JsonObject;
  rerank?: JsonObject;
  coverage_check?: JsonObject;
  retrieved_pages?: number[];
  retrieved_sections?: string[];
  [key: string]: JsonValue | undefined;
}

export interface EvidenceBundle {
  text_chunks?: JsonValue[];
  section_summaries?: JsonValue[];
  abstract_chunks?: JsonValue[];
  tables?: JsonValue[];
  figures?: JsonValue[];
  pages?: JsonValue[];
  [key: string]: JsonValue[] | undefined;
}

export interface NoteGenerationSummary {
  mode?: string;
  template_version?: string;
  repair_rounds?: number;
  note_chunks?: number;
  note_vector_status?: string;
  vector_backend?: string;
  markdown_path?: string;
  pdf_attachment_path?: string;
  quality_check?: JsonValue;
  repair_log?: JsonValue;
  evidence_group_counts?: JsonValue;
  [key: string]: JsonValue | undefined;
}

export interface ExecutionPayload {
  harness?: HarnessExecution;
  harness_decisions?: JsonValue[];
  graph_state?: GraphStateSummary;
  langgraph_nodes?: JsonValue[];
  mcp_tool_calls?: JsonValue[];
  a2a_messages?: JsonValue[];
  skill_phases?: JsonValue[];
  model_execution?: JsonValue;
  rag_evidence?: JsonValue[];
  evidence_bundle?: EvidenceBundle;
  rag_pipeline?: JsonValue;
  retrieval?: RetrievalSummary;
  note_generation?: NoteGenerationSummary;
  vision_execution?: JsonObject;
  pdf_image_extraction?: JsonObject;
  fallbacks?: JsonValue[];
}
