from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import config
from harness.context_manager import redact_value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@contextmanager
def connect() -> Iterable[sqlite3.Connection]:
    config.ensure_directories()
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def init_db() -> None:
    config.ensure_directories()
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.executescript(schema)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_tasks)").fetchall()}
        if "session_id" not in columns:
            conn.execute("ALTER TABLE agent_tasks ADD COLUMN session_id TEXT")
        if "run_id" not in columns:
            conn.execute("ALTER TABLE agent_tasks ADD COLUMN run_id TEXT")
        if "execution_json" not in columns:
            conn.execute("ALTER TABLE agent_tasks ADD COLUMN execution_json TEXT DEFAULT '{}'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tasks_session_id ON agent_tasks(session_id)")
        ensure_columns(
            conn,
            "paper_chunks",
            {
                "source_type": "TEXT DEFAULT 'text'",
                "section_id": "TEXT",
                "section_path": "TEXT",
                "page_start": "INTEGER",
                "page_end": "INTEGER",
                "context_prefix": "TEXT",
                "metadata_json": "TEXT",
                "is_abstract": "INTEGER DEFAULT 0",
                "retrieval_weight": "REAL DEFAULT 1.0",
                "chunk_role": "TEXT DEFAULT ''",
                "section_role": "TEXT DEFAULT ''",
            },
        )
        ensure_columns(
            conn,
            "document_sections",
            {
                "is_abstract": "INTEGER DEFAULT 0",
                "section_role": "TEXT DEFAULT ''",
                "detection_confidence": "REAL DEFAULT 0.0",
                "boundary_source": "TEXT DEFAULT ''",
            },
        )
        ensure_columns(
            conn,
            "document_chunks",
            {
                "is_abstract": "INTEGER DEFAULT 0",
                "retrieval_weight": "REAL DEFAULT 1.0",
                "chunk_role": "TEXT DEFAULT ''",
                "parent_section_role": "TEXT DEFAULT ''",
            },
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_chunks_source_type ON paper_chunks(source_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_chunks_page ON paper_chunks(page_start, page_end)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_source_type ON document_chunks(source_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_page ON document_chunks(page_start, page_end)")
        existing = conn.execute("SELECT id FROM folders WHERE id = ?", ("folder_all",)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO folders (id, name, is_system, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("folder_all", "All Papers", 1, now_iso(), now_iso()),
            )
        session = conn.execute("SELECT id FROM chat_sessions WHERE id = ?", ("session_default",)).fetchone()
        if not session:
            now = now_iso()
            conn.execute(
                "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("session_default", "默认对话", now, now),
            )
        conn.execute("UPDATE agent_tasks SET session_id = ? WHERE session_id IS NULL OR session_id = ''", ("session_default",))
        conn.execute(
            """
            UPDATE chat_sessions
            SET title = ?
            WHERE id = ?
              AND NOT EXISTS (SELECT 1 FROM agent_tasks WHERE session_id = chat_sessions.id)
            """,
            ("默认对话", "session_default"),
        )


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def log_trace(conn: sqlite3.Connection, task_id: str, step_index: int, node: str, agent: str, action: str, summary: str, status: str = "ok") -> dict[str, Any]:
    item = {
        "id": new_id("trace"),
        "task_id": task_id,
        "step_index": step_index,
        "node_name": node,
        "agent_name": agent,
        "action_type": action,
        "summary": redact_secrets(summary)[:800],
        "status": status,
        "created_at": now_iso(),
    }
    conn.execute(
        """
        INSERT INTO agent_traces
        (id, task_id, step_index, node_name, agent_name, action_type, summary, status, created_at)
        VALUES (:id, :task_id, :step_index, :node_name, :agent_name, :action_type, :summary, :status, :created_at)
        """,
        item,
    )
    return item


def log_mcp(conn: sqlite3.Connection, task_id: str, server: str, tool: str, input_summary: str, output_summary: str, status: str = "ok", error: str = "", latency_ms: int = 0) -> dict[str, Any]:
    item = {
        "id": new_id("mcp"),
        "task_id": task_id,
        "server_name": server,
        "tool_name": tool,
        "input_summary": redact_secrets(input_summary)[:800],
        "output_summary": redact_secrets(output_summary)[:800],
        "status": status,
        "error": redact_secrets(error)[:800],
        "latency_ms": latency_ms,
        "created_at": now_iso(),
    }
    conn.execute(
        """
        INSERT INTO mcp_tool_calls
        (id, task_id, server_name, tool_name, input_summary, output_summary, status, error, latency_ms, created_at)
        VALUES (:id, :task_id, :server_name, :tool_name, :input_summary, :output_summary, :status, :error, :latency_ms, :created_at)
        """,
        item,
    )
    return item


def redact_secrets(value: Any) -> str:
    text = redact_value(value, 2000)
    for secret in [config.OPENAI_API_KEY, config.DEEPSEEK_API_KEY, config.GEMINI_API_KEY]:
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"sk-[A-Za-z0-9*_-]{8,}", "[redacted-api-key]", text)
    return text


def log_a2a(conn: sqlite3.Connection, task_id: str, from_agent: str, to_agent: str, message_type: str, payload: dict[str, Any], status: str = "delivered") -> dict[str, Any]:
    item = {
        "id": new_id("a2a"),
        "task_id": task_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "message_type": message_type,
        "payload": redact_secrets(payload)[:2000],
        "status": status,
        "created_at": now_iso(),
    }
    conn.execute(
        """
        INSERT INTO a2a_messages
        (id, task_id, from_agent, to_agent, message_type, payload, status, created_at)
        VALUES (:id, :task_id, :from_agent, :to_agent, :message_type, :payload, :status, :created_at)
        """,
        item,
    )
    return item
