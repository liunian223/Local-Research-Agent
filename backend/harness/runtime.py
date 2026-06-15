from __future__ import annotations

from typing import Any, Callable

from database import connect, new_id, now_iso, row_to_dict
from graph.builder import initial_phase, standard_flow, validate_node_visits
from harness.execution_builder import build_task_execution, save_task_execution


class RuntimeTaskError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def run_upload_task(
    *,
    file_bytes: bytes,
    file_name: str,
    folder_id: str,
    session_id: str,
    message: str,
    task_type_resolver: Callable[..., str],
    ensure_session_fn: Callable[[Any, str | None], str],
    touch_session_fn: Callable[[Any, str, str], None],
    upload_graph_runner: Callable[[Any, str, str, bytes, str, str, str], dict[str, Any]],
    execution_builder: Callable[..., dict[str, Any]] = build_task_execution,
    save_execution_fn: Callable[[Any, str, dict[str, Any]], None] = save_task_execution,
) -> dict[str, Any]:
    """Runtime entrypoint for PDF upload/import tasks.

    The first implementation intentionally reuses the existing graph runner
    callback so the business flow stays unchanged while API endpoints get thin.
    """
    task_id = new_id("task")
    run_id = new_id("run")
    task_type = task_type_resolver(message, has_upload=True)
    with connect() as conn:
        resolved_session_id = ensure_session_fn(conn, session_id)
        conn.execute(
            "INSERT INTO agent_tasks (id, task_type, user_input, status, current_folder_id, session_id, run_id, chat_scope, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, task_type, message, "running", folder_id, resolved_session_id, run_id, "paper_and_note", now_iso(), now_iso()),
        )
        final_state = upload_graph_runner(conn, task_id, task_type, file_bytes, file_name, folder_id, message)
        paper = final_state.get("paper", {})
        answer = final_state.get("answer") or "任务执行中止：检测到异常循环。"
        message_type = final_state.get("message_type") or "assistant_answer"
        evidence = final_state.get("rag_evidence", [])
        skill_phases = final_state.get("skill_phases", [])
        fallbacks = final_state.get("fallbacks", [])
        conn.execute("UPDATE agent_tasks SET status = ?, current_paper_id = ?, answer = ?, updated_at = ? WHERE id = ?", ("done", paper["id"], answer, now_iso(), task_id))
        touch_session_fn(conn, resolved_session_id, message or paper.get("title", "") or file_name or "")
        execution = execution_builder(
            conn,
            task_id,
            evidence,
            skill_phases,
            fallbacks,
            final_state.get("retrieval") or final_state.get("retrieve_meta") or {},
            paper.get("id"),
            final_state.get("note_generation") or {},
        )
        save_execution_fn(conn, task_id, execution)
    return {
        "task_id": task_id,
        "answer": answer,
        "message_type": message_type,
        "current_paper": {"paper_id": paper["id"], "title": paper["title"]},
        "artifacts": {
            "markdown_path": paper.get("obsidian_note_path", ""),
            "pdf_path": paper["file_path"],
            "obsidian_pdf_path": paper.get("obsidian_pdf_path", ""),
        },
        "execution": execution,
    }


def run_chat_task(
    *,
    payload: Any,
    task_type_resolver: Callable[[str], str],
    ensure_session_fn: Callable[[Any, str | None], str],
    touch_session_fn: Callable[[Any, str, str], None],
    chat_graph_runner: Callable[[Any, str, Any, dict[str, Any] | None], dict[str, Any]],
    execution_builder: Callable[..., dict[str, Any]] = build_task_execution,
    save_execution_fn: Callable[[Any, str, dict[str, Any]], None] = save_task_execution,
) -> dict[str, Any]:
    """Runtime entrypoint for chat, note-generation, and QA tasks."""
    task_id = new_id("task")
    run_id = new_id("run")
    task_type = task_type_resolver(payload.message)
    with connect() as conn:
        resolved_session_id = ensure_session_fn(conn, payload.session_id)
        conn.execute(
            "INSERT INTO agent_tasks (id, task_type, user_input, status, current_paper_id, current_folder_id, session_id, run_id, chat_scope, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, task_type, payload.message, "running", payload.current_paper_id, payload.current_folder_id, resolved_session_id, run_id, payload.chat_scope, now_iso(), now_iso()),
        )
        paper = None
        if payload.current_paper_id:
            paper = row_to_dict(conn.execute("SELECT * FROM papers WHERE id = ?", (payload.current_paper_id,)).fetchone())
        if task_type == "generate_note" and not paper:
            raise RuntimeTaskError(400, "current_paper_required", "Generating a note requires a current paper.")

        final_state = chat_graph_runner(conn, task_id, payload, paper)
        evidence = final_state.get("rag_evidence", [])
        skill_phases = final_state.get("skill_phases", [])
        fallbacks = final_state.get("fallbacks", [])
        answer = final_state.get("answer") or "任务执行中止：检测到异常循环。"
        message_type = final_state.get("message_type") or "assistant_answer"

        conn.execute("UPDATE agent_tasks SET status = ?, answer = ?, updated_at = ? WHERE id = ?", ("done", answer, now_iso(), task_id))
        touch_session_fn(conn, resolved_session_id, payload.message)
        execution = execution_builder(
            conn,
            task_id,
            evidence,
            skill_phases,
            fallbacks,
            final_state.get("retrieval") or final_state.get("retrieve_meta") or {},
            paper.get("id") if paper else None,
            final_state.get("note_generation") or {},
        )
        save_execution_fn(conn, task_id, execution)
    return {
        "task_id": task_id,
        "answer": answer,
        "message_type": message_type,
        "current_paper": {"paper_id": paper["id"], "title": paper["title"]} if paper else None,
        "artifacts": {
            "markdown_path": paper.get("obsidian_note_path", "") if paper else "",
            "pdf_path": paper.get("file_path", "") if paper else "",
            "obsidian_pdf_path": paper.get("obsidian_pdf_path", "") if paper else "",
        },
        "execution": execution,
    }


__all__ = [
    "RuntimeTaskError",
    "initial_phase",
    "run_chat_task",
    "run_upload_task",
    "standard_flow",
    "validate_node_visits",
]
