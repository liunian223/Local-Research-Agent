from __future__ import annotations

import sqlite3
from typing import Any

from database import new_id, now_iso
from harness.context_manager import redact_value


def log_harness_decision(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    stage: str,
    decision: str,
    reason: str = "",
    agent: str = "",
    tool: str = "",
    status: str = "ok",
) -> dict[str, Any]:
    item = {
        "id": new_id("decision"),
        "task_id": task_id,
        "stage": stage,
        "decision": decision,
        "reason": redact_value(reason or "", 800),
        "agent": agent or "",
        "tool": tool or "",
        "status": status or "ok",
        "created_at": now_iso(),
    }
    conn.execute(
        """
        INSERT INTO harness_decisions
        (id, task_id, stage, decision, reason, agent, tool, status, created_at)
        VALUES (:id, :task_id, :stage, :decision, :reason, :agent, :tool, :status, :created_at)
        """,
        item,
    )
    return item

