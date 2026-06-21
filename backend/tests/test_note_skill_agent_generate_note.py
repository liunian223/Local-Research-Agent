from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import harness.agent_service as agent_service
from app import app
from database import connect
from deepseek_client import LLMResult
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


class FakeNoteModelGateway:
    def __init__(self, responses: list[LLMResult]) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def generate_text(self, prompt: str, system: str = "", purpose: str = "chat", temperature: float = 0.2, max_output_tokens: int | None = None, image_paths: list[str] | None = None) -> LLMResult:
        self.calls.append(list(image_paths or []))
        if self.responses:
            return self.responses.pop(0)
        return LLMResult(ok=False, content="", model="codex:default", error="unexpected extra call")


def note_pdf(tmp_path: Path, name: str) -> Path:
    return make_pdf(
        tmp_path,
        name,
        (
            "Retry Note Paper\nTeam\nAbstract\n"
            "This paper tests retry note generation with abstract evidence.\n\n"
            "I. INTRODUCTION\nThe introduction motivates retry behavior.\n\n"
            "II. RELATED WORK\nRelated work compares multimodal and text-only note generation.\n\n"
            "III. METHOD\nThe method uses final evidence text, figure captions, table captions, and nearby text.\n\n"
            "IV. EXPERIMENT\nThe experiment evaluates retry handling.\n\n"
            "V. RESULTS\nThe results show the text-only retry can complete the note.\n\n"
            "VI. CONCLUSION\nThe conclusion summarizes reliability improvements."
        ),
    )


def install_successful_note_mocks(monkeypatch, fake_gateway: FakeNoteModelGateway, images_allowed: bool = True) -> None:
    monkeypatch.setattr(agent_service, "get_model_gateway", lambda: fake_gateway)
    monkeypatch.setattr(agent_service, "check_required_note_sections", lambda markdown: {"ok": True, "required_sections_present": True, "missing_sections": []})
    monkeypatch.setattr(
        agent_service,
        "assess_note_evidence_coverage",
        lambda evidence: {
            "ok": True,
            "section_counts": {"abstract": 1, "introduction": 1, "method": 1, "experiment": 1, "result": 1, "conclusion": 1},
            "body_section_counts": {"abstract": 1, "introduction": 1, "method": 1, "experiment": 1, "result": 1, "conclusion": 1},
            "missing_key_evidence": [],
            "missing_body_evidence": [],
            "missing_many_key_sections": False,
        },
    )
    monkeypatch.setattr(
        agent_service,
        "collect_note_image_context",
        lambda conn, paper_id, evidence: ([f"C:\\fake\\figure_{idx}.png" for idx in range(6)], "Figure caption, table caption, and nearby_text evidence."),
    )
    monkeypatch.setattr(agent_service, "codex_vision_probe_allows_note_images", lambda: (images_allowed, {"vision_probe_status": "ok" if images_allowed else "failed"}))


def test_multimodal_note_failure_retries_text_only_success_done(monkeypatch, tmp_path: Path) -> None:
    fake_gateway = FakeNoteModelGateway(
        [
            LLMResult(ok=False, content="", model="codex:default", error="returncode=1"),
            LLMResult(ok=True, content="# Model Note\n\nDone", model="codex:default", usage_summary="provider=codex; images=0"),
        ]
    )
    install_successful_note_mocks(monkeypatch, fake_gateway, images_allowed=True)
    with TestClient(app) as client:
        response = post_pdf(client, note_pdf(tmp_path, "retry_success.pdf"), message="note")

    body = response.json()
    execution = body["execution"]
    assert response.status_code == 200
    assert execution["note_generation"]["status"] == "done"
    assert execution["note_generation"]["llm_note_generation_status"] == "ok"
    assert execution["note_generation"]["local_template_used"] is False
    assert execution["harness"]["runtime_status"] == "done"
    assert fake_gateway.calls == [[f"C:\\fake\\figure_{idx}.png" for idx in range(6)], []]
    assert "multimodal_failed_text_retry_succeeded" in execution["fallbacks"]
    assert "llm_note_generation_failed_local_note_used" not in execution["fallbacks"]
    assert execution["model_execution"]["first_model_attempt"] == "codex_multimodal"
    assert execution["model_execution"]["first_model_attempt_status"] == "failed"
    assert execution["model_execution"]["retry_model_attempt"] == "codex_text_only"
    assert execution["model_execution"]["retry_model_attempt_status"] == "ok"
    assert execution["model_execution"]["image_count_attempted"] == 6


def test_multimodal_note_failure_and_text_only_failure_uses_local_template(monkeypatch, tmp_path: Path) -> None:
    fake_gateway = FakeNoteModelGateway(
        [
            LLMResult(ok=False, content="", model="codex:default", error="returncode=1"),
            LLMResult(ok=False, content="", model="codex:default", error="text retry failed"),
        ]
    )
    install_successful_note_mocks(monkeypatch, fake_gateway, images_allowed=True)
    with TestClient(app) as client:
        response = post_pdf(client, note_pdf(tmp_path, "retry_failure.pdf"), message="note")

    execution = response.json()["execution"]
    assert execution["note_generation"]["status"] == "partial"
    assert execution["note_generation"]["local_template_used"] is True
    assert execution["harness"]["runtime_status"] == "partial"
    assert fake_gateway.calls == [[f"C:\\fake\\figure_{idx}.png" for idx in range(6)], []]
    assert "llm_note_generation_failed_local_note_used" in execution["fallbacks"]
    assert any("model_note_generation failed" in reason for reason in execution["note_generation"]["downgrade_reasons"])
    assert execution["model_execution"]["retry_model_attempt_status"] == "error"


def test_vision_unavailable_goes_directly_text_only(monkeypatch, tmp_path: Path) -> None:
    fake_gateway = FakeNoteModelGateway([LLMResult(ok=True, content="# Text Note\n\nDone", model="codex:default", usage_summary="provider=codex; images=0")])
    install_successful_note_mocks(monkeypatch, fake_gateway, images_allowed=False)
    with TestClient(app) as client:
        response = post_pdf(client, note_pdf(tmp_path, "vision_unavailable.pdf"), message="note")

    execution = response.json()["execution"]
    assert execution["note_generation"]["status"] == "done"
    assert execution["harness"]["runtime_status"] == "done"
    assert fake_gateway.calls == [[]]
    assert execution["model_execution"]["first_model_attempt"] == "codex_text_only"
    assert execution["model_execution"]["retry_model_attempt_status"] == "not_called"
    assert execution["model_execution"]["image_count_attempted"] == 0
    assert "llm_note_generation_failed_local_note_used" not in execution["fallbacks"]
