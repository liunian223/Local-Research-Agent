from __future__ import annotations

import re
from typing import Any


REDACTED_FIELDS = ["api_key", "uploaded_file_bytes", "full_paper_text", "raw_pdf_bytes", "paper_text", "note_markdown"]


def context_pack_strategy(task_type: str, chat_scope: str = "") -> str:
    if task_type in {"paper_chat"}:
        return "evidence_bundle_first"
    if task_type == "global_chat" or chat_scope == "global_library":
        return "global_evidence_bundle_first"
    if task_type in {"generate_note", "import_and_note"}:
        return "note_evidence_bundle_first"
    if task_type == "import_paper":
        return "metadata_and_parse_status_only"
    return "evidence_bundle_first"


def redact_value(value: Any, limit: int = 800) -> str:
    text = value if isinstance(value, str) else _summarize(value)
    for field in REDACTED_FIELDS:
        text = re.sub(rf"(?i)({re.escape(field)}=)[^,\n;]+", rf"\1<redacted>", text)
    text = re.sub(r"sk-[A-Za-z0-9*_-]{8,}", "[redacted-api-key]", text)
    text = re.sub(r"(?i)(api[_-]?key=)[^,\s]+", r"\1[redacted]", text)
    return text[:limit]


def redaction_summary() -> dict[str, Any]:
    return {"enabled": True, "redacted_fields": REDACTED_FIELDS}


def _summarize(value: Any) -> str:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        if len(value) > 1600:
            return f"<{len(value)} chars>"
        return value
    if isinstance(value, dict):
        parts = []
        for key, item in list(value.items())[:12]:
            lower = key.lower()
            if lower in {"uploaded_file_bytes", "paper_text", "raw_pdf_bytes", "note_markdown"} or "api_key" in lower:
                parts.append(f"{key}=<redacted>")
            else:
                parts.append(f"{key}={_summarize(item)[:120]}")
        return ", ".join(parts)
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}(len={len(value)})"
    return str(value)
