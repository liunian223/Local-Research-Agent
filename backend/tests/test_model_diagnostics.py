from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import config
import harness.agent_service as agent_service
from app import app
from database import connect, init_db, new_id, now_iso
from deepseek_client import DeepSeekClient, LLMResult
from harness.execution_builder import build_task_execution
from tool_gateway import ToolGateway


def test_model_diagnostics_without_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "TEXT_MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")

    with TestClient(app) as client:
        response = client.get("/api/model/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "deepseek"
    assert payload["key_present"] is False
    assert payload["fallback_enabled"] is True


def test_model_error_is_structured(monkeypatch) -> None:
    init_db()

    class FakeModelGateway:
        def generate_text(self, *args, **kwargs):
            return LLMResult(
                ok=False,
                content="",
                model="deepseek-chat",
                error="request timed out",
                provider="deepseek",
                stage="chat",
                error_type="timeout_error",
                retryable=True,
            )

    monkeypatch.setattr(agent_service, "get_model_gateway", lambda: FakeModelGateway())
    task_id = new_id("task")
    now = now_iso()
    evidence = [{"section_name": "Methods", "text": "SSVEP evidence text.", "rank": 1, "source_type": "paper"}]
    fallbacks = []
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_tasks
            (id, task_type, user_input, status, current_paper_id, current_folder_id, session_id, run_id, chat_scope, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, "chat", "question", "done", "paper_1", "folder_all", "session_default", "run_model_error", "paper_only", now, now),
        )
        gateway = ToolGateway(conn, task_id)
        answer = agent_service.synthesize_answer_with_optional_llm(gateway, task_id, "question", evidence, fallbacks)
        execution = build_task_execution(conn, task_id, evidence=evidence, skill_phases=[], fallbacks=fallbacks, paper_id="paper_1")

    structured = [item for item in fallbacks if isinstance(item, dict)]
    assert "timeout_error" in answer
    assert structured
    assert structured[0]["error_type"] == "timeout_error"
    assert structured[0]["provider"] == "deepseek"
    assert any(decision["decision"] == "model_chat_failed_local_rag_answer_used" for decision in execution["harness_decisions"])
    assert any(decision["reason"] == "request timed out" for decision in execution["harness_decisions"])


def test_json_probe_fallback() -> None:
    class FakeCompletions:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if "response_format" in kwargs:
                raise ValueError("response_format json_object unsupported")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            )

    fake_completions = FakeCompletions()
    client = DeepSeekClient.__new__(DeepSeekClient)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))

    result = client.json_chat([{"role": "user", "content": 'Return JSON {"ok": true}'}], model="deepseek-chat", max_tokens=64)

    assert result["ok"] is True
    assert fake_completions.calls == 2
    assert result["_fallbacks"][0]["type"] == "json_response_format_unsupported"
