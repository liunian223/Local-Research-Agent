from __future__ import annotations

from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
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

    is_long_paper: bool
    section_summaries: dict[str, Any]
    note_plan: dict[str, Any]
    partial_note_sections: dict[str, str]
    note_markdown: Optional[str]
    note_quality_check: dict[str, Any]
    note_repair_rounds: int

    answer: Optional[str]
    message_type: str
    artifacts: dict[str, Any]

    langgraph_nodes: list[dict[str, Any]]
    mcp_tool_calls: list[dict[str, Any]]
    a2a_messages: list[dict[str, Any]]
    skill_phases: list[dict[str, Any]]
    fallbacks: list[Any]

    status: str
    error: Optional[str]
