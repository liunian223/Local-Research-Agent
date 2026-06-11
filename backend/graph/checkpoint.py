from __future__ import annotations

from copy import deepcopy
from typing import Any


def snapshot_state(state: dict[str, Any]) -> dict[str, Any]:
    safe = deepcopy(state)
    if safe.get("uploaded_file_bytes"):
        safe["uploaded_file_bytes"] = f"<{len(safe['uploaded_file_bytes'])} bytes>"
    if safe.get("paper_text"):
        safe["paper_text"] = f"<{len(safe['paper_text'])} chars>"
    return safe
