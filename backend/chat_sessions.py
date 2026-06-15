from __future__ import annotations

import json
from typing import Any

from database import connect, new_id, now_iso, row_to_dict, rows_to_dicts


PLACEHOLDER_TITLES = {"", "新对话", "默认对话", "榛樿瀵硅瘽", "鏂板璇?", "칵훰뚤뺐"}


def history_message_text(task: dict[str, Any]) -> str:
    if task.get("user_input"):
        return task["user_input"]
    if task.get("task_type") in {"import_paper", "import_and_note"}:
        return "上传 PDF"
    return ""


def parse_execution_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def ensure_session(conn: Any, session_id: str | None = None) -> str:
    resolved = session_id or "session_default"
    session = conn.execute("SELECT id FROM chat_sessions WHERE id = ?", (resolved,)).fetchone()
    if not session:
        now = now_iso()
        conn.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (resolved, "默认对话" if resolved == "session_default" else "新对话", now, now),
        )
    return resolved


def session_title_from_message(message: str) -> str:
    clean = " ".join(message.split()).strip()
    if not clean:
        return "新对话"
    return clean[:24]


def touch_session(conn: Any, session_id: str, title_hint: str = "") -> None:
    session = conn.execute("SELECT title FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    title = session["title"] if session else "新对话"
    if title in PLACEHOLDER_TITLES and title_hint:
        title = session_title_from_message(title_hint)
    conn.execute("UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?", (title, now_iso(), session_id))


def session_display_row(row: dict[str, Any]) -> dict[str, Any]:
    task_count = int(row.get("task_count") or 0)
    title = (row.get("title") or "").strip()
    if title in PLACEHOLDER_TITLES and task_count > 0:
        display_title = f"已有对话（{task_count} 条记录）"
    elif title in PLACEHOLDER_TITLES:
        display_title = "默认对话" if row.get("id") == "session_default" else "新对话"
    else:
        display_title = title
    return {**row, "task_count": task_count, "has_messages": task_count > 0, "display_title": display_title}


def list_sessions() -> dict[str, Any]:
    with connect() as conn:
        ensure_session(conn)
        rows = conn.execute(
            """
            SELECT s.*, COUNT(t.id) AS task_count
            FROM chat_sessions s
            LEFT JOIN agent_tasks t ON t.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
    return {"sessions": [session_display_row(row) for row in rows_to_dicts(rows)]}


def create_session(title: str) -> dict[str, Any]:
    now = now_iso()
    session = {"id": new_id("session"), "title": title.strip() or "新对话", "created_at": now, "updated_at": now}
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (:id, :title, :created_at, :updated_at)",
            session,
        )
    return {"session": session}


def delete_session(session_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        session = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            return None
        task_ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM agent_tasks WHERE session_id = ?", (session_id,)).fetchall()
        ]
        if task_ids:
            placeholders = ",".join("?" for _ in task_ids)
            conn.execute(f"DELETE FROM agent_traces WHERE task_id IN ({placeholders})", task_ids)
            conn.execute(f"DELETE FROM a2a_messages WHERE task_id IN ({placeholders})", task_ids)
            conn.execute(f"DELETE FROM mcp_tool_calls WHERE task_id IN ({placeholders})", task_ids)
            conn.execute(f"DELETE FROM agent_tasks WHERE id IN ({placeholders})", task_ids)
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        remaining = conn.execute("SELECT id FROM chat_sessions ORDER BY updated_at DESC LIMIT 1").fetchone()
        next_session_id = remaining["id"] if remaining else ensure_session(conn)
    return {"status": "deleted", "deleted_tasks": len(task_ids), "next_session_id": next_session_id}


def get_history(limit: int = 50, session_id: str = "session_default") -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    with connect() as conn:
        resolved_session_id = ensure_session(conn, session_id)
        rows = conn.execute(
            """
            SELECT * FROM agent_tasks
            WHERE status = 'done' AND session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (resolved_session_id, limit),
        ).fetchall()
        tasks = list(reversed(rows_to_dicts(rows)))
        messages: list[dict[str, Any]] = []
        for task in tasks:
            user_text = history_message_text(task)
            if user_text:
                messages.append({"role": "user", "text": user_text, "content": user_text, "task_id": task["id"]})
            if task.get("answer"):
                assistant_message = {"role": "assistant", "text": task["answer"], "content": task["answer"], "task_id": task["id"]}
                execution = parse_execution_json(task.get("execution_json"))
                if execution:
                    assistant_message["execution"] = execution
                messages.append(assistant_message)

        latest = tasks[-1] if tasks else {}
        paper = None
        if latest.get("current_paper_id"):
            paper = row_to_dict(conn.execute("SELECT * FROM papers WHERE id = ?", (latest["current_paper_id"],)).fetchone())
            if paper:
                note = conn.execute(
                    "SELECT id, obsidian_path, created_at, updated_at FROM reading_notes WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1",
                    (paper["id"],),
                ).fetchone()
                paper["latest_note"] = row_to_dict(note)
    return {
        "messages": messages,
        "current_paper": paper,
        "current_folder_id": latest.get("current_folder_id") or (paper.get("folder_id") if paper else "folder_all"),
        "chat_scope": latest.get("chat_scope") or "paper_and_note",
        "session_id": resolved_session_id,
    }
