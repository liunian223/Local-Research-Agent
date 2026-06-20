from __future__ import annotations

from pathlib import Path

import config
from database import connect, init_db, new_id, now_iso
from harness.execution_builder import build_task_execution
from llm.model_gateway import get_model_gateway


def test_codex_demo_model_execution_does_not_show_openai_vision(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "codex")
    monkeypatch.setattr(config, "TEXT_MODEL_PROVIDER", "codex")
    monkeypatch.setattr(config, "VISION_MODEL_PROVIDER", "codex")
    monkeypatch.setattr(config, "DISABLE_OPENAI_API", True)
    monkeypatch.setattr(config, "ENABLE_OPENAI_VISION", False)
    monkeypatch.setattr(config, "CODEX_MODEL_VISION", "")

    info = get_model_gateway().model_execution_info()

    assert info["vision_model_provider"] == "codex"
    assert info["vision_model"] == "codex:default"
    assert info["openai_vision_enabled"] is False


def test_disable_openai_api_overrides_openai_vision_provider_for_display(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "codex")
    monkeypatch.setattr(config, "TEXT_MODEL_PROVIDER", "codex")
    monkeypatch.setattr(config, "VISION_MODEL_PROVIDER", "openai")
    monkeypatch.setattr(config, "DISABLE_OPENAI_API", True)
    monkeypatch.setattr(config, "ENABLE_OPENAI_VISION", True)

    info = get_model_gateway().model_execution_info()

    assert info["vision_model_provider"] != "openai"
    assert info["vision_model_provider"] == "codex"
    assert info["vision_model"] == "codex:default"
    assert info["openai_vision_enabled"] is False


def test_codex_vision_mcp_summary_matches_model_execution(monkeypatch, tmp_path: Path) -> None:
    init_db()
    monkeypatch.setattr(config, "LLM_PROVIDER", "codex")
    monkeypatch.setattr(config, "TEXT_MODEL_PROVIDER", "codex")
    monkeypatch.setattr(config, "VISION_MODEL_PROVIDER", "codex")
    monkeypatch.setattr(config, "DISABLE_OPENAI_API", True)
    monkeypatch.setattr(config, "ENABLE_OPENAI_VISION", False)
    task_id = new_id("task")
    now = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_tasks
            (id, task_type, user_input, status, current_paper_id, current_folder_id, session_id, run_id, chat_scope, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, "vision_chat", "Explain figure 1", "done", "paper_meta", "folder_all", "session_default", "run_meta", "paper_only", now, now),
        )
        conn.execute(
            """
            INSERT INTO mcp_tool_calls
            (id, task_id, server_name, tool_name, input_summary, output_summary, status, error, latency_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id("mcp"), task_id, "llm", "codex_vision_chat", "codex:default; images=2", "provider=codex; images=2", "ok", "", 1, now),
        )
        execution = build_task_execution(
            conn,
            task_id,
            evidence=[],
            skill_phases=[],
            fallbacks=[],
            retrieval={},
            paper_id="paper_meta",
            vision_execution={"status": "success", "codex_vision_status": "success"},
        )

    info = execution["model_execution"]
    assert info["vision_model_provider"] == "codex"
    assert info["openai_vision_enabled"] is False
    assert any(
        call["tool_name"] == "codex_vision_chat"
        and "images=2" in call["input_summary"]
        and call["status"] == "ok"
        for call in execution["mcp_tool_calls"]
    )
