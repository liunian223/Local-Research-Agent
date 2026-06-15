from __future__ import annotations

from fastapi.testclient import TestClient

from app import app
from database import connect, init_db, new_id, now_iso


def test_chat_history_restores_saved_execution() -> None:
    init_db()
    session_id = new_id("session")
    task_id = new_id("task")
    now = now_iso()
    execution = '{"harness":{"runtime_status":"done"},"retrieval":{"retrieval_mode":"simple_retrieve_rerank"}}'
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, "history execution", now, now),
        )
        conn.execute(
            """
            INSERT INTO agent_tasks
            (id, task_type, user_input, answer, status, session_id, run_id, chat_scope, execution_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, "paper_chat", "question", "answer", "done", session_id, "run_history", "paper_only", execution, now, now),
        )

    with TestClient(app) as client:
        response = client.get("/api/chat/history", params={"session_id": session_id})

    assert response.status_code == 200
    messages = response.json()["messages"]
    assistant = next(message for message in messages if message["role"] == "assistant")
    assert assistant["content"] == "answer"
    assert assistant["text"] == "answer"
    assert assistant["execution"]["harness"]["runtime_status"] == "done"


def test_chat_history_ignores_invalid_execution_json() -> None:
    init_db()
    session_id = new_id("session")
    task_id = new_id("task")
    now = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, "bad execution", now, now),
        )
        conn.execute(
            """
            INSERT INTO agent_tasks
            (id, task_type, user_input, answer, status, session_id, run_id, chat_scope, execution_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, "paper_chat", "question", "answer", "done", session_id, "run_bad", "paper_only", "{bad", now, now),
        )

    with TestClient(app) as client:
        response = client.get("/api/chat/history", params={"session_id": session_id})

    assert response.status_code == 200
    assistant = next(message for message in response.json()["messages"] if message["role"] == "assistant")
    assert "execution" not in assistant
