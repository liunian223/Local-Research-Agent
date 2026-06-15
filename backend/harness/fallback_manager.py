from __future__ import annotations

from typing import Any


def runtime_error_fallback(state: dict[str, Any], exc: Exception) -> dict[str, Any]:
    state["phase"] = "ERROR"
    state["status"] = "failed"
    state["error"] = str(exc)
    state.setdefault("fallbacks", []).append({"type": "runtime_error", "message": str(exc)[:300]})
    return state
