from __future__ import annotations

from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    run_id: str
    session_id: str
    user_input: str
    task_type: str

    phase: str
    needs_evidence: bool
    evidence_ready: bool
    note_ready: bool
    import_done: bool
    node_visit_count: dict[str, int]

    current_folder_id: Optional[str]
    current_paper_id: Optional[str]
    current_note_id: Optional[str]
    chat_scope: str

    uploaded_file_bytes: Optional[bytes]
    uploaded_file_path: Optional[str]
    original_file_name: Optional[str]
    paper_metadata: dict[str, Any]
    paper_text: str
    page_count: int
    parse_status: str
    parse_warning: str
    metadata_warning: str

    paper: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]
    rag_evidence: list[dict[str, Any]]
    retrieve_meta: dict[str, Any]
    retrieval: dict[str, Any]
    rag_pipeline: dict[str, Any]
    evidence_bundle: dict[str, Any]

    image_assets: list[dict[str, Any]]
    selected_image_paths: list[str]
    rendered_image_paths: list[str]
    vision_required: bool
    vision_answer: str
    vision_execution: dict[str, Any]
    pdf_image_extraction: dict[str, Any]

    is_long_paper: bool
    section_summaries: dict[str, Any]
    note_plan: dict[str, Any]
    note_generation: dict[str, Any]
    note_generation_mode: str
    note_evidence_bundle: dict[str, Any]
    note_template_version: str
    partial_note_sections: dict[str, str]
    note_markdown: Optional[str]
    note_quality_check: dict[str, Any]
    note_repair_rounds: int
    note_repair_log: list[dict[str, Any]]
    note_id: Optional[str]
    note_chunks: list[dict[str, Any]]
    note_vector_status: str
    obsidian_note_path: Optional[str]
    obsidian_pdf_path: Optional[str]

    answer: Optional[str]
    message_type: str
    artifacts: dict[str, Any]

    langgraph_nodes: list[dict[str, Any]]
    mcp_tool_calls: list[dict[str, Any]]
    a2a_messages: list[dict[str, Any]]
    skill_phases: list[dict[str, Any]]
    fallbacks: list[Any]

    status: str
    task_status: str
    error: Optional[str]

    harness: dict[str, Any]
    harness_context: dict[str, Any]
    policy_checks: list[dict[str, Any]]
    tool_summary: dict[str, Any]
    context_pack_strategy: str
    redacted_fields: list[str]
    execution_harness: dict[str, Any]
    runtime_warnings: list[dict[str, Any]]
