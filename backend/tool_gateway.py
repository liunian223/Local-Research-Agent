from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from database import log_mcp
from harness.context_manager import redact_value
from harness.decisions import log_harness_decision
from harness.policy import POLICY_RULES, check_tool_policy


class ToolGateway:
    """In-process MCP-style tool gateway with policy checks and call logging."""

    POLICY = POLICY_RULES

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
        policy_check = self._check_policy(agent_name, server_name, tool_name)
        started = time.perf_counter()
        summarized_input = input_summary or summarize_value(args or kwargs)
        input_with_policy = f"{summarized_input}; policy={_json_policy(policy_check)}"
        try:
            result = func(*args, **kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            output_summary = output_summarizer(result) if output_summarizer else summarize_value(result)
            log_mcp(
                self.conn,
                self.task_id,
                server_name,
                tool_name,
                input_with_policy,
                redact_value(output_summary),
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
                input_with_policy,
                "Tool call failed.",
                status="error",
                error=str(exc),
                latency_ms=latency_ms,
            )
            raise

    def _check_policy(self, agent_name: str, server_name: str, tool_name: str) -> dict[str, Any]:
        policy_check = check_tool_policy(agent_name, server_name, tool_name)
        if not policy_check["allowed"]:
            log_harness_decision(
                self.conn,
                self.task_id,
                stage="tool_policy",
                decision="deny",
                reason=policy_check["reason"],
                agent=agent_name,
                tool=f"{server_name}.{tool_name}",
                status="denied",
            )
            raise PermissionError(policy_check["reason"])
        log_harness_decision(
            self.conn,
            self.task_id,
            stage="tool_policy",
            decision="allow",
            reason=policy_check["reason"],
            agent=agent_name,
            tool=f"{server_name}.{tool_name}",
            status="ok",
        )
        return policy_check


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
                parts.append(f"{key}={redact_value(item, 120)}")
        return redact_value(", ".join(parts), 800)
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}(len={len(value)})"
    return redact_value(repr(value), 800)


def _json_policy(policy_check: dict[str, Any]) -> str:
    import json

    return json.dumps(policy_check, ensure_ascii=False, separators=(",", ":"))
