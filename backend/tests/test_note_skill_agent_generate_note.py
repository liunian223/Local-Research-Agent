from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app import app
from database import connect
from tests.test_acceptance import make_pdf, post_pdf


def test_note_generation_execution_contains_note_status_and_index(tmp_path: Path) -> None:
    unique_marker = uuid4().hex
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            f"note_agent_{unique_marker}.pdf",
            (
                f"Note Agent Paper {unique_marker}\nTeam\nAbstract\n"
                "This paper tests Note Skill Agent evidence bundle handling and note indexing.\n\n"
                "I. INTRODUCTION\nThe introduction motivates the note generation retrieval problem.\n\n"
                "II. RELATED WORK\nRelated work compares structured RAG and local note generation.\n\n"
                "III. METHOD\nThe method uses chapterized retrieval with body text chunks.\n\n"
                "IV. EXPERIMENT\nThe experiment evaluates evidence coverage and indexing.\n\n"
                "V. RESULTS\nThe results show accuracy and performance improvements over baselines.\n\n"
                "VI. CONCLUSION\nIn conclusion, future work should reduce limitations."
            ),
        )
        response = post_pdf(client, pdf, message="note")
        assert response.status_code == 200
        assert response.json()["message_type"] == "partial_success"
        assert "Downgrade reason:" in response.json()["answer"]
        execution = response.json()["execution"]
        note_generation = execution["note_generation"]
        assert execution["harness"]["runtime_status"] == "partial"
        assert execution["harness"]["latency_ms"] > 0
        assert execution["retrieval"]["retrieval_mode"] == "note_chapterized_plan"
        assert execution["retrieval"]["retrieval_intent"] == "generate_note"
        assert execution["retrieval"]["retrieval_plan"]["mode"] == "note_chapterized_plan"
        assert note_generation["status"] == "partial"
        assert note_generation["local_template_used"] is True
        assert "llm_note_generation_failed_local_note_used" in execution["fallbacks"]
        assert execution["retrieval"]["abstract_control"]["abstract_chunks_used"] == len(execution["evidence_bundle"].get("abstract_chunks", []))
        assert execution["retrieval"]["evidence_stats"]["text_chunks"] == len(execution["evidence_bundle"].get("text_chunks", []))
        assert len(execution["evidence_bundle"].get("text_chunks", [])) > 0
        assert len(execution["evidence_bundle"].get("abstract_chunks", [])) > 0
        assert len(execution["retrieval"]["final_note_evidence_bundle"].get("text_chunks", [])) > 0
        assert len(execution["retrieval"]["final_note_evidence_bundle"].get("abstract_chunks", [])) > 0
        assert execution["retrieval"]["final_note_evidence_bundle"]["text_chunks"] == execution["evidence_bundle"]["text_chunks"]
        assert "section_summaries" not in note_generation["quality_check"]
        assert "template_quality_check" in note_generation["quality_check"]
        assert "section_summary_quality_check" in note_generation["quality_check"]
        assert "evidence_coverage_check" in note_generation["quality_check"]
        model_note_calls = [item for item in execution["mcp_tool_calls"] if item["tool_name"] == "model_note_generation"]
        assert model_note_calls
        assert all(item["latency_ms"] > 0 for item in model_note_calls)
        final_a2a = [item for item in execution["a2a_messages"] if item["message_type"] == "final_evidence_bundle_ready"]
        assert final_a2a
        assert "text_chunks=list(len=0)" not in final_a2a[-1]["payload"]
        assert "abstract_chunks=list(len=0)" not in final_a2a[-1]["payload"]
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
