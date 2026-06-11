from __future__ import annotations

from typing import Any

from tool_gateway import ToolGateway


def create_tool_gateway(conn: Any, task_id: str) -> ToolGateway:
    return ToolGateway(conn, task_id)
