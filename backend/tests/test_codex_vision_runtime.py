from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image

import config
from database import connect, init_db, now_iso
from harness.library_service import delete_paper_response
from harness.policy import check_tool_policy
from llm.codex_runtime_client import CodexRuntimeClient
from llm.llm_router import get_llm_client, reset_llm_client_for_tests
from vision.image_asset_selector import question_requires_vision, select_image_assets
from vision.pdf_image_extractor import extract_pdf_images
from vision.pdf_page_renderer import render_pdf_pages


def make_pdf_with_embedded_image(tmp_path: Path) -> Path:
    image = tmp_path / "figure.png"
    Image.new("RGB", (180, 160), color=(120, 40, 200)).save(image)
    pdf = tmp_path / "with_image.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Figure 1. Embedded test image.")
    page.insert_image(fitz.Rect(72, 120, 252, 280), filename=str(image))
    doc.save(pdf)
    doc.close()
    return pdf


def test_llm_router_returns_codex_runtime_without_openai_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "codex")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    reset_llm_client_for_tests()
    client = get_llm_client()
    assert isinstance(client, CodexRuntimeClient)
    reset_llm_client_for_tests()


def test_codex_runtime_error_omits_prompt(monkeypatch) -> None:
    class Completed:
        returncode = 1
        stdout = "OpenAI Codex\nuser\nSECRET PROMPT BODY"
        stderr = "runtime failed"

    monkeypatch.setattr("llm.codex_runtime_client.subprocess.run", lambda *args, **kwargs: Completed())
    client = CodexRuntimeClient(command="codex", timeout_seconds=1)
    try:
        client.chat_sync([{"role": "user", "content": "SECRET PROMPT BODY"}])
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected Codex runtime failure")
    assert "SECRET PROMPT BODY" not in message
    assert "[prompt omitted]" in message


def test_codex_runtime_scrubs_openai_api_env_for_subprocess(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        captured["env"] = kwargs.get("env") or {}
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("OK", encoding="utf-8")
        return Completed()

    monkeypatch.setenv("OPENAI_API_KEY", "dummy-openai-key-not-forwarded")
    monkeypatch.setattr(config, "DISABLE_OPENAI_API", True)
    monkeypatch.setattr("llm.codex_runtime_client.subprocess.run", fake_run)
    client = CodexRuntimeClient(command="codex", timeout_seconds=1)
    assert client.chat_sync([{"role": "user", "content": "hello"}]) == "OK"
    assert "OPENAI_API_KEY" not in captured["env"]


def test_codex_runtime_command_includes_skip_git_check(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("OK", encoding="utf-8")
        return Completed()

    monkeypatch.setattr("llm.codex_runtime_client.subprocess.run", fake_run)
    client = CodexRuntimeClient(command="codex", timeout_seconds=1)
    assert client.chat_sync([{"role": "user", "content": "hello"}]) == "OK"
    assert "--skip-git-repo-check" in captured["command"]


def test_pdf_image_extractor_and_renderer_create_assets(tmp_path: Path) -> None:
    pdf = make_pdf_with_embedded_image(tmp_path)
    paper_id = "paper_test_image"
    extracted = extract_pdf_images(pdf, paper_id)
    assert extracted["status"] in {"success", "partial"}
    assert extracted["assets"]
    assert Path(extracted["assets"][0]["image_path"]).exists()
    assert extracted["assets"][0]["source_type"] == "embedded_image"

    rendered = render_pdf_pages(pdf, paper_id, [1])
    assert rendered["status"] == "success"
    assert rendered["assets"][0]["source_type"] == "rendered_page"
    assert Path(rendered["assets"][0]["image_path"]).exists()


def test_selector_renders_page_when_no_embedded_assets(tmp_path: Path) -> None:
    init_db()
    pdf = tmp_path / "text_only.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Page 1 method diagram placeholder.")
    doc.save(pdf)
    doc.close()
    paper_id = "paper_selector"
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO papers
            (id, title, file_path, file_sha256, folder_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (paper_id, "Selector Paper", str(pdf), "selector_sha", "folder_all", now_iso(), now_iso()),
        )
        result = select_image_assets(
            conn,
            paper_id=paper_id,
            question="Explain page 1 diagram",
            evidence=[{"page_start": 1, "text": "diagram evidence"}],
            pdf_path=str(pdf),
        )
    assert result["selected_image_paths"]
    assert result["render_status"] == "success"
    assert result["selected_assets"][0]["source_type"] == "rendered_page"


def test_question_requires_vision_keywords() -> None:
    assert question_requires_vision("解释这篇论文中的图 1")
    assert question_requires_vision("What does Fig. 2 show?")
    assert not question_requires_vision("summarize the introduction")


def test_policy_allows_pdf_vision_tools() -> None:
    assert check_tool_policy("Knowledge RAG Agent", "vision", "extract_pdf_images")["allowed"]
    assert check_tool_policy("Knowledge RAG Agent", "database", "insert_image_assets")["allowed"]
    assert check_tool_policy("Note Skill Agent", "llm", "codex_vision_chat")["allowed"]


def test_delete_paper_removes_vision_directories(tmp_path: Path) -> None:
    init_db()
    paper_id = "paper_delete_vision"
    pdf = tmp_path / "delete_vision.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    image_dir = config.PDF_IMAGE_DIR / paper_id
    rendered_dir = config.PDF_RENDERED_PAGE_DIR / paper_id
    image_dir.mkdir(parents=True, exist_ok=True)
    rendered_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "page_001_img_001.png").write_bytes(b"image")
    (rendered_dir / "page_001.png").write_bytes(b"image")
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO papers
            (id, title, file_path, file_sha256, folder_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (paper_id, "Delete Vision Paper", str(pdf), "delete_vision_sha", "folder_all", now_iso(), now_iso()),
        )
    response = delete_paper_response(paper_id)
    assert response["status"] == "deleted"
    assert not image_dir.exists()
    assert not rendered_dir.exists()
