from __future__ import annotations

import pytest

from database import connect, init_db, new_id, rows_to_dicts
from tool_gateway import ToolGateway


def test_tool_gateway_logs_policy_checked_call() -> None:
    init_db()
    task_id = new_id("task")
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_tasks (id, task_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, "paper_chat", "running", "now", "now"),
        )
        gateway = ToolGateway(conn, task_id)
        assert gateway.invoke("Knowledge RAG Agent", "rag", "adaptive_retrieve", lambda: "ok") == "ok"
        rows = rows_to_dicts(conn.execute("SELECT * FROM mcp_tool_calls WHERE task_id = ?", (task_id,)).fetchall())
    assert rows
    assert "policy=" in rows[0]["input_summary"]


def test_tool_gateway_denies_forbidden_tool() -> None:
    init_db()
    with connect() as conn:
        gateway = ToolGateway(conn, "task_missing")
        with pytest.raises(PermissionError):
            gateway.invoke("Knowledge RAG Agent", "skills", "run_deep_paper_note_skill", lambda: "bad")
