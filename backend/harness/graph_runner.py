from __future__ import annotations

from typing import Any, Callable

from agents.knowledge_rag_agent import knowledge_rag_agent_node
from agents.note_skill_agent import note_skill_agent_node
from database import log_trace, new_id
from graph.builder import initial_phase, run_graph
from graph.state import AgentState
from harness.context_manager import context_pack_strategy
from tool_gateway import ToolGateway


GraphHandler = Callable[[AgentState, ToolGateway], AgentState]


def run_upload_agent_graph(
    *,
    conn: Any,
    task_id: str,
    task_type: str,
    file_bytes: bytes,
    file_name: str,
    folder_id: str,
    message: str,
    import_handler: GraphHandler,
    retrieve_handler: GraphHandler,
    generate_note_handler: GraphHandler,
    answer_chat_handler: GraphHandler,
) -> AgentState:
    state: AgentState = {
        "task_id": task_id,
        "run_id": new_id("run"),
        "user_input": message,
        "task_type": task_type,
        "phase": "START",
        "current_folder_id": folder_id,
        "chat_scope": "paper_and_note",
        "context_pack_strategy": context_pack_strategy(task_type, "paper_and_note"),
        "harness": {"runtime_status": "running"},
        "uploaded_file_bytes": file_bytes,
        "original_file_name": file_name,
        "fallbacks": [],
        "skill_phases": [],
        "rag_evidence": [],
        "artifacts": {},
        "status": "running",
    }
    return _run_agent_graph(
        conn=conn,
        task_id=task_id,
        task_type=task_type,
        state=state,
        import_handler=import_handler,
        retrieve_handler=retrieve_handler,
        retrieve_trace_summary="phase=REQUEST_EVIDENCE",
        generate_note_handler=generate_note_handler,
        answer_chat_handler=answer_chat_handler,
    )


def run_chat_agent_graph(
    *,
    conn: Any,
    task_id: str,
    task_type: str,
    message: str,
    current_paper_id: str | None,
    current_folder_id: str | None,
    chat_scope: str,
    paper: dict[str, Any] | None,
    import_handler: GraphHandler,
    retrieve_handler: GraphHandler,
    generate_note_handler: GraphHandler,
    answer_chat_handler: GraphHandler,
) -> AgentState:
    state: AgentState = {
        "task_id": task_id,
        "run_id": new_id("run"),
        "user_input": message,
        "task_type": task_type,
        "phase": "START",
        "current_paper_id": current_paper_id,
        "current_folder_id": current_folder_id,
        "chat_scope": chat_scope,
        "context_pack_strategy": context_pack_strategy(task_type, chat_scope),
        "harness": {"runtime_status": "running"},
        "paper": paper or {},
        "fallbacks": [],
        "skill_phases": [],
        "rag_evidence": [],
        "artifacts": {
            "markdown_path": paper.get("obsidian_note_path", "") if paper else "",
            "pdf_path": paper.get("file_path", "") if paper else "",
        },
        "status": "running",
    }
    return _run_agent_graph(
        conn=conn,
        task_id=task_id,
        task_type=task_type,
        state=state,
        import_handler=import_handler,
        retrieve_handler=retrieve_handler,
        retrieve_trace_summary=f"scope={chat_scope}",
        generate_note_handler=generate_note_handler,
        answer_chat_handler=answer_chat_handler,
    )


def _run_agent_graph(
    *,
    conn: Any,
    task_id: str,
    task_type: str,
    state: AgentState,
    import_handler: GraphHandler,
    retrieve_handler: GraphHandler,
    retrieve_trace_summary: str,
    generate_note_handler: GraphHandler,
    answer_chat_handler: GraphHandler,
) -> AgentState:
    gateway = ToolGateway(conn, task_id)
    step = {"value": 1}

    def trace(node: str, agent: str, action: str, summary: str) -> None:
        log_trace(conn, task_id, step["value"], node, agent, action, summary)
        step["value"] += 1

    trace("coordinator_node", "Harness", "route_task", f"task_type={task_type}; phase={initial_phase(task_type)}")

    def traced_import_handler(inner: AgentState) -> AgentState:
        trace("knowledge_rag_agent_node", "Knowledge RAG Agent", "import_paper", "phase=IMPORT_PAPER")
        return import_handler(inner, gateway)

    def traced_retrieve_handler(inner: AgentState) -> AgentState:
        trace("knowledge_rag_agent_node", "Knowledge RAG Agent", "retrieve_evidence", retrieve_trace_summary)
        return retrieve_handler(inner, gateway)

    def traced_generate_note_handler(inner: AgentState) -> AgentState:
        trace("note_skill_agent_node", "Note Skill Agent", "generate_note", "phase=EVIDENCE_READY")
        return generate_note_handler(inner, gateway)

    def traced_answer_chat_handler(inner: AgentState) -> AgentState:
        trace("note_skill_agent_node", "Note Skill Agent", "answer_chat", "phase=EVIDENCE_READY")
        return answer_chat_handler(inner, gateway)

    final_state = run_graph(
        state,
        lambda inner: knowledge_rag_agent_node(inner, traced_import_handler, traced_retrieve_handler),
        lambda inner: note_skill_agent_node(inner, traced_generate_note_handler, traced_answer_chat_handler),
    )
    trace("finish_node", "Harness", "finish", f"phase={final_state.get('phase')}; status={final_state.get('status')}")
    return final_state


__all__ = ["run_chat_agent_graph", "run_upload_agent_graph"]
