from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from database import connect
from tests.test_acceptance import make_pdf, post_pdf


def test_note_generation_execution_contains_note_status_and_index(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "note_agent_v14.pdf",
            "Note Agent Paper\nTeam\nAbstract\nThis paper tests Note Skill Agent evidence bundle handling and note indexing.",
        )
        response = post_pdf(client, pdf, message="note")
        assert response.status_code == 200
        assert response.json()["message_type"] == "partial_success"
        assert "Downgrade reason:" in response.json()["answer"]
        execution = response.json()["execution"]
        note_generation = execution["note_generation"]
        assert execution["harness"]["runtime_status"] == "partial"
        assert note_generation["status"] == "partial"
        assert note_generation["local_template_used"] is True
        assert "llm_note_generation_failed_local_note_used" in execution["fallbacks"]
        assert note_generation["template_version"] == "obsidian_note_v2"
        assert note_generation["note_chunks"] > 0
        assert note_generation["note_vector_status"] in {"done", "fallback_index_recorded"}
        paper_id = response.json()["current_paper"]["paper_id"]
        with connect() as conn:
            paper = conn.execute("SELECT note_status FROM papers WHERE id = ?", (paper_id,)).fetchone()
            task = conn.execute("SELECT status FROM agent_tasks WHERE id = ?", (response.json()["task_id"],)).fetchone()
        assert paper["note_status"] == "partial"
        assert task["status"] == "partial"
        tools = {(item["server_name"], item["tool_name"]) for item in execution["mcp_tool_calls"]}
        assert ("database", "insert_note") in tools
        assert ("database", "insert_note_chunks") in tools
        assert ("database", "update_paper_status") in tools
