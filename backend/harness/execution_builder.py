from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from database import now_iso, row_to_dict, rows_to_dicts
from graph.builder import initial_phase, standard_flow, validate_node_visits
from llm.model_gateway import get_model_gateway
from structured_retriever import build_evidence_bundle, rag_pipeline_summary

from .context_manager import context_pack_strategy, redaction_summary


def build_harness_execution(
    task: dict[str, Any],
    mcp_calls: list[dict[str, Any]],
    fallbacks: list[Any],
    policy_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    summary = summarize_tool_calls(mcp_calls)
    latency_ms = max(summary.get("total_latency_ms", 0), task_duration_ms(task))
    return {
        "task_id": task.get("id"),
        "run_id": task.get("run_id") or f"run_{task.get('id', '')}",
        "session_id": task.get("session_id") or "",
        "runtime_status": task.get("status") or "unknown",
        "task_type": task.get("task_type") or "",
        "chat_scope": task.get("chat_scope") or "",
        "current_paper_id": task.get("current_paper_id") or "",
        "context_pack_strategy": context_pack_strategy(task.get("task_type") or "", task.get("chat_scope") or ""),
        "policy_checks": policy_checks if policy_checks is not None else policy_checks_from_mcp(mcp_calls),
        "tool_summary": summary,
        "redaction": redaction_summary(),
        "fallbacks": fallbacks,
        "latency_ms": latency_ms,
    }


def build_task_execution(
    conn: Any,
    task_id: str,
    evidence: list[dict[str, Any]],
    skill_phases: list[dict[str, Any]],
    fallbacks: list[Any],
    retrieval: dict[str, Any] | None = None,
    paper_id: str | None = None,
    note_generation: dict[str, Any] | None = None,
    vision_execution: dict[str, Any] | None = None,
    pdf_image_extraction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    traces = rows_to_dicts(conn.execute("SELECT * FROM agent_traces WHERE task_id = ? ORDER BY step_index ASC", (task_id,)).fetchall())
    mcp = rows_to_dicts(conn.execute("SELECT * FROM mcp_tool_calls WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall())
    a2a = rows_to_dicts(conn.execute("SELECT * FROM a2a_messages WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall())
    task = row_to_dict(conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()) or {}
    visited = [trace["node_name"] for trace in traces]
    visits_ok, visits_error = validate_node_visits(visited)
    retrieval_meta = retrieval or {}
    evidence_bundle = retrieval_meta.get("final_note_evidence_bundle") or build_evidence_bundle(evidence, retrieval_meta)
    return {
        "harness": build_harness_execution(task, mcp, fallbacks),
        "graph_state": {
            "task_type": task.get("task_type"),
            "initial_phase": initial_phase(task.get("task_type", "")),
            "standard_flow": standard_flow(task.get("task_type", "")),
            "node_visit_limit_ok": visits_ok,
            "node_visit_limit_error": visits_error,
        },
        "langgraph_nodes": traces,
        "mcp_tool_calls": mcp,
        "a2a_messages": a2a,
        "skill_phases": skill_phases,
        "model_execution": get_model_gateway().model_execution_info(),
        "rag_evidence": evidence,
        "evidence_bundle": evidence_bundle,
        "rag_pipeline": rag_pipeline_summary(conn, paper_id or task.get("current_paper_id")),
        "retrieval": retrieval_meta,
        "note_generation": note_generation or {},
        "vision_execution": vision_execution or {},
        "pdf_image_extraction": pdf_image_extraction or {},
        "fallbacks": fallbacks,
    }


def save_task_execution(conn: Any, task_id: str, execution: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE agent_tasks SET execution_json = ?, run_id = COALESCE(NULLIF(run_id, ''), ?), updated_at = ? WHERE id = ?",
        (json.dumps(execution, ensure_ascii=False), execution.get("harness", {}).get("run_id", ""), now_iso(), task_id),
    )


def summarize_tool_calls(mcp_calls: list[dict[str, Any]]) -> dict[str, Any]:
    by_server: dict[str, int] = {}
    failed = 0
    latency = 0
    for call in mcp_calls:
        server = call.get("server_name") or "unknown"
        by_server[server] = by_server.get(server, 0) + 1
        if call.get("status") not in {"ok", "success"}:
            failed += 1
        latency += int(call.get("latency_ms") or 0)
    return {
        "total_calls": len(mcp_calls),
        "failed_calls": failed,
        "mcp_servers": sorted(by_server),
        "calls_by_server": by_server,
        "total_latency_ms": latency,
    }


def task_duration_ms(task: dict[str, Any]) -> int:
    try:
        created = datetime.fromisoformat(str(task.get("created_at") or ""))
        updated = datetime.fromisoformat(str(task.get("updated_at") or ""))
    except Exception:
        return 0
    return max(0, int((updated - created).total_seconds() * 1000))


def policy_checks_from_mcp(mcp_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for call in mcp_calls:
        parsed = _load_policy(call.get("input_summary") or "")
        if parsed:
            checks.append(parsed)
    return checks


def _load_policy(summary: str) -> dict[str, Any] | None:
    marker = "policy="
    if marker not in summary:
        return None
    try:
        payload = summary.split(marker, 1)[1].strip()
        return json.loads(payload)
    except Exception:
        return None
