from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import config


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
        existing = conn.execute("SELECT id FROM folders WHERE id = ?", ("folder_all",)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO folders (id, name, is_system, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("folder_all", "All Papers", 1, now_iso(), now_iso()),
            )


def log_trace(conn: sqlite3.Connection, task_id: str, step_index: int, node: str, agent: str, action: str, summary: str, status: str = "ok") -> dict[str, Any]:
    item = {
        "id": new_id("trace"),
        "task_id": task_id,
        "step_index": step_index,
        "node_name": node,
        "agent_name": agent,
        "action_type": action,
        "summary": summary[:800],
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
        "input_summary": input_summary[:800],
        "output_summary": output_summary[:800],
        "status": status,
        "error": error[:800],
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


def log_a2a(conn: sqlite3.Connection, task_id: str, from_agent: str, to_agent: str, message_type: str, payload: dict[str, Any], status: str = "delivered") -> dict[str, Any]:
    item = {
        "id": new_id("a2a"),
        "task_id": task_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "message_type": message_type,
        "payload": json.dumps(payload, ensure_ascii=False)[:2000],
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
