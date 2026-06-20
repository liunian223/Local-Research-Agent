from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import config
from app import app
from database import connect, init_db, now_iso
from deepseek_client import LLMResult


class Completed:
    def __init__(self, returncode: int = 0, stdout: str = "OK", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_codex_run(args, **kwargs):
    if "--version" in args:
        return Completed(stdout="codex-cli 0.test\n")
    if "--image" in args:
        return Completed(stdout="vision OK\n")
    return Completed(stdout="OK\n")


def fake_run_command(args, stdin, timeout_seconds, **kwargs):
    if "--version" in args:
        return Completed(stdout="codex-cli 0.test\n")
    if "--image" in args:
        return Completed(stdout="vision OK\n")
    return Completed(stdout="OK\n")


def test_text_probe_timeout_after_ok_is_success(monkeypatch) -> None:
    def fake_run(args, stdin, timeout_seconds, **kwargs):
        if "--version" in args:
            return Completed(stdout="codex-cli 0.test\n")
        return Completed(returncode=124, stdout="OK\n", stderr="Timed out")

    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run)
    with TestClient(app) as client:
        body = client.get("/api/codex/health?run_probes=true").json()
    assert body["text_ok"] is True
    assert body["text_warning"] == "Codex produced output but process timed out after output."
    assert body["timed_out_after_output"] is True


def test_vision_probe_timeout_after_description_is_success(monkeypatch, tmp_path: Path) -> None:
    image = tmp_path / "probe.png"
    image.write_bytes(b"png")

    def fake_run(args, stdin, timeout_seconds, **kwargs):
        if "--version" in args:
            return Completed(stdout="codex-cli 0.test\n")
        if "--image" in args:
            return Completed(returncode=124, stdout="A simple paper page titled Vision Demo Paper.", stderr="Timed out")
        return Completed(stdout="OK\n")

    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics.latest_vision_png", lambda: image)
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run)
    with TestClient(app) as client:
        body = client.get("/api/codex/health?run_probes=true").json()
    assert body["vision_ok"] is True
    assert body["vision_warning"] == "Codex produced output but process timed out after output."
    assert body["timed_out_after_output"] is True


def test_auth_error_recommends_login(monkeypatch) -> None:
    def fake_run(args, stdin, timeout_seconds, **kwargs):
        if "--version" in args:
            return Completed(stdout="codex-cli 0.test\n")
        return Completed(returncode=1, stdout="", stderr="401 Unauthorized: Missing bearer")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run)
    with TestClient(app) as client:
        body = client.get("/api/codex/health?run_probes=true").json()
    assert "login" in body["recommendation"].lower()


def test_trusted_directory_error_recommends_skip_git_check(monkeypatch) -> None:
    def fake_run(args, stdin, timeout_seconds, **kwargs):
        if "--version" in args:
            return Completed(stdout="codex-cli 0.test\n")
        return Completed(returncode=1, stdout="", stderr="Not inside a trusted directory")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run)
    with TestClient(app) as client:
        body = client.get("/api/codex/health?run_probes=true").json()
    assert "--skip-git-repo-check" in body["recommendation"]


def test_utf8_probe_output_is_preserved(monkeypatch) -> None:
    def fake_run(args, stdin, timeout_seconds, **kwargs):
        if "--version" in args:
            return Completed(stdout="codex-cli 0.test\n")
        return Completed(returncode=1, stdout="Vision Demo Paper 标题正常", stderr="")

    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run)
    with TestClient(app) as client:
        body = client.get("/api/codex/health?run_probes=true").json()
    assert "标题正常" in body["text_error_summary"]
    assert "â" not in body["text_error_summary"]


def test_codex_health_openai_env_present_does_not_leak_value(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run_command)
    with TestClient(app) as client:
        body = client.get("/api/codex/health").json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert body["env_openai_api_key_present"] is True
    assert "sk-test-secret-value" not in serialized


def test_codex_health_auth_json_does_not_leak_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    auth_dir = tmp_path / ".codex"
    auth_dir.mkdir()
    (auth_dir / "auth.json").write_text(
        json.dumps({"auth_mode": "api_key", "openai_api_key": "sk-hidden", "last_refresh": "today"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run_command)
    with TestClient(app) as client:
        body = client.get("/api/codex/health").json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert body["auth_cache_found"] is True
    assert body["suspected_auth_mode"] == "api_key"
    assert "openai_api_key" not in body["auth_cache_top_level_keys"]
    assert "sk-hidden" not in serialized


def test_codex_health_command_missing_returns_structured_result(monkeypatch) -> None:
    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: None)
    with TestClient(app) as client:
        response = client.get("/api/codex/health")
    assert response.status_code == 200
    body = response.json()
    assert body["codex_found"] is False
    assert body["text_ok"] is False


def test_codex_health_unknown_auth_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    auth_dir = tmp_path / ".codex"
    auth_dir.mkdir()
    (auth_dir / "auth.json").write_text(json.dumps({"auth_mode": "custom", "last_refresh": "today"}), encoding="utf-8")
    monkeypatch.setattr("llm.codex_diagnostics.shutil.which", lambda command: "C:\\Tools\\codex.cmd")
    monkeypatch.setattr("llm.codex_diagnostics._run_command", fake_run_command)
    with TestClient(app) as client:
        body = client.get("/api/codex/health").json()
    assert body["suspected_auth_mode"] == "unknown"


def test_vision_nonzero_returns_fallback_not_500(monkeypatch, tmp_path: Path) -> None:
    init_db()
    paper_id = "paper_codex_health_fallback"
    image_dir = config.PDF_IMAGE_DIR / paper_id
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / "page_001_img_001.png"
    image_path.write_bytes(b"png")
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    now = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO papers
            (id, title, file_path, file_sha256, folder_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (paper_id, "Fallback Paper", str(pdf_path), "fallback_sha", "folder_all", now, now),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO image_assets
            (id, paper_id, page_no, image_index, image_path, source_type, width, height, caption, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("img_fallback", paper_id, 1, 1, str(image_path), "embedded_image", 10, 10, "", now),
        )

    class FakeGateway:
        def generate_text(self, *args, **kwargs):
            return LLMResult(ok=False, content="", model="codex:test", error='{"returncode":1,"stderr":"failed","stdout":""}')

        def model_execution_info(self):
            return {}

    monkeypatch.setattr("harness.agent_service.get_model_gateway", lambda: FakeGateway())
    with TestClient(app) as client:
        response = client.post(
            "/api/chat/message",
            json={"message": "Explain figure 1", "current_paper_id": paper_id, "chat_scope": "paper_only"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["execution"]["graph_state"]["task_type"] == "vision_chat"
    assert body["execution"]["vision_execution"]["status"] == "fallback"
    assert any(isinstance(item, dict) and item.get("type") == "codex_vision_failed" for item in body["execution"]["fallbacks"])
