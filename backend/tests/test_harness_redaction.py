from __future__ import annotations

from database import connect, init_db, log_a2a, log_trace, new_id
from harness.context_manager import redact_value, redaction_summary


def test_harness_redacts_api_keys_and_large_fields() -> None:
    text = redact_value({"OPENAI_API_KEY": "sk-123456789abcdef", "paper_text": "x" * 5000})
    assert "sk-123456789abcdef" not in text
    assert "<redacted>" in text
    assert "paper_text=<redacted>" in text
    assert "uploaded_file_bytes" in redaction_summary()["redacted_fields"]


def test_trace_and_a2a_logs_use_shared_redaction() -> None:
    init_db()
    task_id = new_id("task")
    with connect() as conn:
        trace = log_trace(conn, task_id, 1, "node", "agent", "action", "api_key=sk-123456789abcdef; paper_text=" + "x" * 5000)
        a2a = log_a2a(conn, task_id, "A", "B", "payload", {"uploaded_file_bytes": b"123", "note_markdown": "secret"})

    assert "sk-123456789abcdef" not in trace["summary"]
    assert "paper_text=<redacted>" in trace["summary"]
    assert "uploaded_file_bytes=<redacted>" in a2a["payload"]
    assert "secret" not in a2a["payload"]
