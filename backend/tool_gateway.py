from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from database import log_mcp


class ToolGateway:
    """In-process MCP-style tool gateway with policy checks and call logging."""

    POLICY = {
        "Knowledge RAG Agent": {"file", "database", "rag"},
        "Note Skill Agent": {"a2a", "skills", "file", "database", "rag", "llm"},
        "Harness": {"file", "database", "rag", "skills", "llm", "a2a"},
    }

    def __init__(self, conn: Any, task_id: str) -> None:
        self.conn = conn
        self.task_id = task_id

    def invoke(
        self,
        agent_name: str,
        server_name: str,
        tool_name: str,
        func: Callable[..., Any],
        *args: Any,
        input_summary: str = "",
        output_summarizer: Callable[[Any], str] | None = None,
        **kwargs: Any,
    ) -> Any:
        self._check_policy(agent_name, server_name, tool_name)
        started = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            output_summary = output_summarizer(result) if output_summarizer else summarize_value(result)
            log_mcp(
                self.conn,
                self.task_id,
                server_name,
                tool_name,
                input_summary or summarize_value(args or kwargs),
                output_summary,
                status="ok",
                latency_ms=latency_ms,
            )
            return result
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            log_mcp(
                self.conn,
                self.task_id,
                server_name,
                tool_name,
                input_summary or summarize_value(args or kwargs),
                "Tool call failed.",
                status="error",
                error=str(exc),
                latency_ms=latency_ms,
            )
            raise

    def _check_policy(self, agent_name: str, server_name: str, tool_name: str) -> None:
        allowed = self.POLICY.get(agent_name, set())
        if server_name not in allowed:
            raise PermissionError(f"{agent_name} is not allowed to call {server_name}.{tool_name}")


def summarize_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, (str, int, float, bool)):
        return str(value)[:800]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return f"{len(value)} bytes"
    if isinstance(value, dict):
        parts = []
        for key, item in list(value.items())[:8]:
            if key.lower().endswith("text") or key.lower() in {"content", "paper_text"}:
                parts.append(f"{key}=<{len(str(item))} chars>")
            else:
                parts.append(f"{key}={str(item)[:80]}")
        return ", ".join(parts)[:800]
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}(len={len(value)})"
    return repr(value)[:800]
