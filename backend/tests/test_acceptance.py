from __future__ import annotations

import os
import sys
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_ROOT = Path(tempfile.mkdtemp(prefix="local_research_agent_tests_"))
os.environ["LOCAL_RESEARCH_AGENT_ENV"] = "test"
os.environ["DATABASE_PATH"] = str(TEST_ROOT / "test.db")
os.environ["DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["PAPER_DIR"] = str(TEST_ROOT / "data" / "papers")
os.environ["PARSED_DIR"] = str(TEST_ROOT / "data" / "parsed")
os.environ["VECTOR_DIR"] = str(TEST_ROOT / "data" / "vector_store")
os.environ["OBSIDIAN_VAULT_PATH"] = str(TEST_ROOT / "vault")
os.environ["VECTOR_BACKEND"] = "local_keyword"
os.environ["TEXT_MODEL_PROVIDER"] = "local_fallback"
os.environ["VISION_MODEL_PROVIDER"] = "none"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["OPENAI_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

import fitz
from fastapi.testclient import TestClient
from langgraph.graph import StateGraph

import config
from app import app, collect_note_image_context
from database import connect, now_iso
from graph.builder import build_langgraph_app
from llm.codex_cli_client import CodexCliClient


def make_pdf(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def make_multipage_pdf(tmp_path: Path, name: str, pages: list[str]) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def post_pdf(client: TestClient, path: Path, folder_id: str = "folder_all", message: str = ""):
    with path.open("rb") as handle:
        return client.post(
            "/api/chat/upload",
            data={"current_folder_id": folder_id, "message": message},
            files={"file": (path.name, handle, "application/pdf")},
        )


def test_graph_runtime_uses_installed_langgraph() -> None:
    def knowledge_node(state: dict) -> dict:
        state["phase"] = "IMPORT_DONE"
        return state

    def note_node(state: dict) -> dict:
        state["phase"] = "NOTE_READY"
        return state

    graph_app = build_langgraph_app(knowledge_node, note_node)

    assert StateGraph.__module__.startswith("langgraph.")
    assert graph_app.__class__.__module__.startswith("langgraph.")


def test_health_and_system_folder_rules() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        folders = client.get("/api/folders").json()["folders"]
        assert folders[0]["id"] == "folder_all"
        assert folders[0]["name"] == "All Papers"
        assert folders[0]["is_system"] is True


def test_delete_paper_removes_it_from_library(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "delete_single_paper.pdf",
            "Delete Single Paper\nAlice Test\n2026\nAbstract\nThis paper validates deleting one paper from the library.",
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        deleted = client.delete(f"/api/papers/{paper_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted_papers"] == 1
        assert client.get(f"/api/papers/{paper_id}").status_code == 404


def test_upload_security_rejects_bad_mime_and_bad_pdf_header() -> None:
    with TestClient(app) as client:
        bad_mime = client.post(
            "/api/chat/upload",
            data={"current_folder_id": "folder_all"},
            files={"file": ("bad.pdf", b"%PDF-1.4\n", "text/plain")},
        )
        assert bad_mime.status_code == 400
        assert bad_mime.json()["detail"]["error"]["code"] == "invalid_mime_type"

        bad_header = client.post(
            "/api/chat/upload",
            data={"current_folder_id": "folder_all"},
            files={"file": ("bad.pdf", b"not a pdf", "application/pdf")},
        )
        assert bad_header.status_code == 400
        assert bad_header.json()["detail"]["error"]["code"] == "invalid_pdf"


def test_upload_two_pdfs_sequentially(tmp_path: Path) -> None:
    with TestClient(app) as client:
        chinese_pdf = make_pdf(
            tmp_path,
            "sequential_chinese.pdf",
            "连续上传中文论文\n作者 A\n2026\n摘要\n这篇论文用于验证第二篇 PDF 上传不会返回 500。",
        )
        english_pdf = make_pdf(
            tmp_path,
            "Human-centred physical neuromorphics with visual brain-computer interfaces.pdf",
            (
                "Human-centred physical neuromorphics with visual brain-computer interfaces\n"
                "Author B\n2026\nAbstract\nThis paper validates sequential English PDF upload after a Chinese paper."
            ),
        )

        first = post_pdf(client, chinese_pdf)
        second = post_pdf(client, english_pdf)
        assert first.status_code == 200
        assert second.status_code == 200

        first_id = first.json()["current_paper"]["paper_id"]
        second_id = second.json()["current_paper"]["paper_id"]
        assert first_id != second_id
        papers = client.get("/api/papers", params={"folder_id": "folder_all"}).json()["papers"]
        paper_ids = {paper["id"] for paper in papers}
        assert {first_id, second_id}.issubset(paper_ids)


def test_upload_duplicate_pdf_returns_existing_or_safe_response(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "duplicate_safe_upload.pdf",
            "Duplicate Safe Upload\nAuthor A\n2026\nAbstract\nThis paper validates duplicate upload handling.",
        )

        first = post_pdf(client, pdf)
        duplicate = post_pdf(client, pdf)
        assert first.status_code == 200
        assert duplicate.status_code == 200
        assert duplicate.json()["current_paper"]["paper_id"] == first.json()["current_paper"]["paper_id"]
        assert "duplicate_pdf_returned_existing_paper" in duplicate.json()["execution"]["fallbacks"]


def test_upload_vector_failure_keeps_paper_and_reports_fallback(tmp_path: Path, monkeypatch) -> None:
    def failing_index_chunks(*args, **kwargs):
        raise RuntimeError("simulated vector failure")

    monkeypatch.setattr("harness.agent_service.VECTOR_STORE.index_chunks", failing_index_chunks)
    with TestClient(app) as client:
        pdf = make_multipage_pdf(
            tmp_path,
            "vector_failure_upload.pdf",
            [
                "Vector Failure Upload\nAuthor A\n2026\nAbstract\n" + ("This abstract contains enough text for extraction. " * 80),
                "Methods\n" + ("This body validates vector fallback handling during upload. " * 120),
            ],
        )

        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        body = upload.json()
        paper_id = body["current_paper"]["paper_id"]
        assert any(
            item.get("type") == "vector_index_failed"
            for item in body["execution"]["fallbacks"]
            if isinstance(item, dict)
        )

        paper = client.get(f"/api/papers/{paper_id}")
        assert paper.status_code == 200
        assert paper.json()["paper"]["vector_status"] == "failed"


def test_import_note_artifacts_execution_and_paper_and_note_scope(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "graph_gateway_rag.pdf",
            (
                "Graph Gateway RAG Paper\nLocal Research Agent Team\n2026\nAbstract\n"
                "This paper discusses graph runner verification, tool gateway records, "
                "RAG evidence retrieval, note chunks, and Obsidian attachment copying."
            ),
        )
        upload = post_pdf(client, pdf, message="note")
        body = upload.json()
        assert upload.status_code == 200
        assert body["message_type"] == "partial_success"
        assert body["execution"]["harness"]["runtime_status"] == "partial"
        assert "llm_note_generation_failed_local_note_used" in body["execution"]["fallbacks"]

        artifacts = body["artifacts"]
        assert Path(artifacts["markdown_path"]).exists()
        assert Path(artifacts["pdf_path"]).exists()
        assert Path(artifacts["obsidian_pdf_path"]).exists()

        nodes = [item["node_name"] for item in body["execution"]["langgraph_nodes"]]
        assert nodes == [
            "coordinator_node",
            "knowledge_rag_agent_node",
            "knowledge_rag_agent_node",
            "note_skill_agent_node",
            "finish_node",
        ]
        assert body["execution"]["graph_state"]["node_visit_limit_ok"] is True

        tools = {(item["server_name"], item["tool_name"]) for item in body["execution"]["mcp_tool_calls"]}
        assert ("file", "save_uploaded_pdf") in tools
        assert ("file", "write_markdown_note") in tools
        assert ("file", "copy_pdf_to_obsidian") in tools
        assert ("skills", "run_deep_paper_note_skill") in tools
        assert ("rag", "build_note_vector_index") in tools

        paper_id = body["current_paper"]["paper_id"]
        chat = client.post(
            "/api/chat/message",
            json={
                "message": "How does the paper discuss graph runner tool gateway RAG evidence?",
                "current_paper_id": paper_id,
                "current_folder_id": "folder_all",
                "chat_scope": "paper_and_note",
            },
        )
        chat_body = chat.json()
        assert chat.status_code == 200
        assert chat_body["message_type"] == "assistant_answer"
        assert chat_body["execution"]["rag_evidence"]
        source_types = {item["source_type"] for item in chat_body["execution"]["rag_evidence"]}
        assert source_types & {"paper", "note"}
        assert chat_body["execution"]["graph_state"]["node_visit_limit_ok"] is True


def test_generated_note_is_listed_under_paper_and_folder_path(tmp_path: Path) -> None:
    with TestClient(app) as client:
        now = now_iso()
        with connect() as conn:
            conn.execute(
                "INSERT INTO folders (id, name, is_system, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("folder_notes", "FolderNotes", 0, now, now),
            )
        pdf = make_pdf(
            tmp_path,
            "folder_note_path.pdf",
            (
                "Folder Note Path Paper\nLocal Research Agent Team\n2026\nAbstract\n"
                "This paper validates that generated notes are shown in the library and stored under folder paths."
            ),
        )
        upload = post_pdf(client, pdf, folder_id="folder_notes", message="note")
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        papers = client.get("/api/papers", params={"folder_id": "folder_notes"}).json()["papers"]
        listed = next(item for item in papers if item["id"] == paper_id)
        assert listed["latest_note"]
        assert Path(listed["latest_note"]["obsidian_path"]).exists()
        assert Path(listed["latest_note"]["obsidian_path"]).parent.name == "FolderNotes"


def test_search_scopes_and_duplicate_pdf_reuse_existing_paper(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "scope_duplicate.pdf",
            (
                "Scope Duplicate Retrieval Paper\nJane Scope, Mark Author\n2026\nAbstract\n"
                "This paper contains a distinctive retrieval keyword: scopefusion. "
                "The generated note should create note chunks for note only retrieval."
            ),
        )
        first = post_pdf(client, pdf, message="note")
        first_body = first.json()
        assert first.status_code == 200
        paper_id = first_body["current_paper"]["paper_id"]

        search_title = client.get("/api/papers/search", params={"keyword": "Scope Duplicate"})
        assert search_title.status_code == 200
        assert any(item["id"] == paper_id for item in search_title.json()["papers"])

        search_author = client.get("/api/papers/search", params={"keyword": "Jane Scope"})
        assert search_author.status_code == 200
        assert any(item["id"] == paper_id for item in search_author.json()["papers"])

        note_only = client.post(
            "/api/chat/message",
            json={
                "message": "scopefusion note chunks",
                "current_paper_id": paper_id,
                "current_folder_id": "folder_all",
                "chat_scope": "note_only",
            },
        )
        assert note_only.status_code == 200
        note_evidence = note_only.json()["execution"]["rag_evidence"]
        assert note_evidence
        assert {item["source_type"] for item in note_evidence} == {"note"}

        global_chat = client.post(
            "/api/chat/message",
            json={
                "message": "scopefusion retrieval keyword",
                "current_paper_id": paper_id,
                "current_folder_id": "folder_all",
                "chat_scope": "global_library",
            },
        )
        assert global_chat.status_code == 200
        assert global_chat.json()["execution"]["rag_evidence"]

        duplicate = post_pdf(client, pdf, message="")
        duplicate_body = duplicate.json()
        assert duplicate.status_code == 200
        assert duplicate_body["current_paper"]["paper_id"] == paper_id
        assert "duplicate_pdf_returned_existing_paper" in duplicate_body["execution"]["fallbacks"]

        all_papers = client.get("/api/papers", params={"folder_id": "folder_all"}).json()["papers"]
        matching = [item for item in all_papers if item["file_sha256"]]
        sha_counts = {}
        for item in matching:
            sha_counts[item["file_sha256"]] = sha_counts.get(item["file_sha256"], 0) + 1
        assert sha_counts[next(item["file_sha256"] for item in matching if item["id"] == paper_id)] == 1


def test_layout_aware_rag_outputs_structured_artifacts_and_metadata(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_multipage_pdf(
            tmp_path,
            "layout_rag.pdf",
            [
                (
                    "Layout Aware RAG Paper\nResearch Team\n2026\nAbstract\n"
                    "This paper introduces layout aware retrieval.\n"
                    "1 Introduction\n"
                    "The introduction explains why page structure matters."
                ),
                (
                    "2 Method\n"
                    "The method section describes semantic chunk construction and section aware retrieval.\n"
                    "Figure 1. Overall architecture of the layout aware paper RAG pipeline.\n"
                    "The nearby text explains that the figure is summarized from caption and surrounding text."
                ),
                (
                    "3 Experiments\n"
                    "Table 1. Dataset statistics.\n"
                    "Dataset  Nodes  Edges\n"
                    "Alpha    10     20\n"
                    "Beta     30     40\n"
                    "The result section reports that metadata-aware retrieval improves grounding."
                ),
            ],
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        parsed_root = config.PARSED_DIR / paper_id
        assert (parsed_root / "layout.json").exists()
        assert (parsed_root / "pages.json").exists()
        assert (parsed_root / "sections.json").exists()
        assert (parsed_root / "chunks.json").exists()

        with connect() as conn:
            page_count = conn.execute("SELECT COUNT(*) AS count FROM document_pages WHERE paper_id = ?", (paper_id,)).fetchone()["count"]
            section_count = conn.execute("SELECT COUNT(*) AS count FROM document_sections WHERE paper_id = ?", (paper_id,)).fetchone()["count"]
            chunk = conn.execute("SELECT * FROM paper_chunks WHERE paper_id = ? AND source_type IN ('text', 'section_summary') LIMIT 1", (paper_id,)).fetchone()
            table_count = conn.execute("SELECT COUNT(*) AS count FROM document_tables WHERE paper_id = ?", (paper_id,)).fetchone()["count"]
            figure_count = conn.execute("SELECT COUNT(*) AS count FROM document_figures WHERE paper_id = ?", (paper_id,)).fetchone()["count"]
            figure = conn.execute("SELECT * FROM document_figures WHERE paper_id = ? LIMIT 1", (paper_id,)).fetchone()
            figure_metadata = json.loads(figure["metadata_json"])
            image_paths, image_context = collect_note_image_context(
                conn,
                paper_id,
                [
                    {
                        "metadata": {
                            "image_path": figure["image_path"],
                            "page_image_path": figure_metadata["page_image_path"],
                            "figure_ids": [figure["id"]],
                        },
                        "section_name": figure["section_path"],
                        "page_start": figure["page_number"],
                    }
                ],
            )
        assert page_count == 3
        assert section_count >= 2
        assert chunk["section_path"]
        assert chunk["page_start"] >= 1
        assert chunk["context_prefix"]
        assert table_count >= 1
        assert figure_count >= 1
        assert figure["image_path"]
        assert (ROOT.parent / figure["image_path"]).exists()
        assert (parsed_root / "pages" / "page_002.png").exists()
        assert len(image_paths) >= 2
        assert "Multimodal image attachments" in image_context


def test_structured_retrieval_modes_for_page_table_and_method(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_multipage_pdf(
            tmp_path,
            "structured_modes.pdf",
            [
                "Structured Retrieval Paper\nTeam\n2026\nAbstract\nThis paper has structured evidence.",
                "2 Method\nThe method builds section summaries and expands related figure evidence.\nFigure 1. Method flow diagram.",
                "3 Experiments\nTable 1. Accuracy results.\nModel  Accuracy\nBase   0.70\nOurs   0.82",
            ],
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        table_chat = client.post(
            "/api/chat/message",
            json={
                "message": "What does Table 1 show?",
                "current_paper_id": paper_id,
                "chat_scope": "paper_only",
            },
        )
        assert table_chat.status_code == 200
        table_execution = table_chat.json()["execution"]
        assert table_execution["retrieval"]["retrieval_mode"] == "table_lookup"
        assert table_execution["evidence_bundle"]["tables"]

        page_chat = client.post(
            "/api/chat/message",
            json={
                "message": "What does page 2 discuss?",
                "current_paper_id": paper_id,
                "chat_scope": "paper_only",
            },
        )
        assert page_chat.status_code == 200
        page_execution = page_chat.json()["execution"]
        assert page_execution["retrieval"]["retrieval_mode"] == "page_lookup"
        assert page_execution["retrieval"]["retrieved_pages"] == [2]

        method_chat = client.post(
            "/api/chat/message",
            json={
                "message": "Explain the method of this paper",
                "current_paper_id": paper_id,
                "chat_scope": "paper_only",
            },
        )
        assert method_chat.status_code == 200
        method_execution = method_chat.json()["execution"]
        assert method_execution["retrieval"]["retrieval_mode"] == "complex_planned_retrieval"
        assert method_execution["retrieval"]["legacy_mode"] == "complex_section_expansion"
        assert method_execution["retrieval"]["retrieved_sections"]


def test_codex_cli_provider_passes_image_arguments(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "figure.png"
    image.write_bytes(b"fake-png")
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("OK", encoding="utf-8")
        return Completed()

    monkeypatch.setattr("llm.codex_cli_client.subprocess.run", fake_run)
    result = CodexCliClient().generate_text("describe the attached figure", image_paths=[str(image)])
    assert result.ok
    command = captured["command"]
    assert "--image" in command
    assert str(image.resolve()) in command
    assert "describe the attached figure" in captured["input"]


def test_chat_history_restores_messages_and_context(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "history_context.pdf",
            (
                "History Context Paper\nLocal Research Agent Team\n2026\nAbstract\n"
                "This paper validates that chat history survives page refresh."
            ),
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        question = "刷新后还能看到这个问题吗"
        chat = client.post(
            "/api/chat/message",
            json={
                "message": question,
                "current_paper_id": paper_id,
                "current_folder_id": "folder_all",
                "chat_scope": "paper_and_note",
            },
        )
        assert chat.status_code == 200

        history = client.get("/api/chat/history")
        assert history.status_code == 200
        body = history.json()
        assert any(item["role"] == "user" and item["text"] == question for item in body["messages"])
        assert any(item["role"] == "assistant" and item["text"] == chat.json()["answer"] for item in body["messages"])
        assert body["current_paper"]["id"] == paper_id
        assert body["current_folder_id"] == "folder_all"
        assert body["chat_scope"] == "paper_and_note"


def test_search_filters_by_current_folder(tmp_path: Path) -> None:
    with TestClient(app) as client:
        now = now_iso()
        with connect() as conn:
            conn.execute(
                "INSERT INTO folders (id, name, is_system, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("folder_search", "SearchFolder", 0, now, now),
            )
        folder_pdf = make_pdf(
            tmp_path,
            "folder_search.pdf",
            "Unique Folder Search Paper\nAlice Test\n2026\nAbstract\nThis paper is only in a folder.",
        )
        library_pdf = make_pdf(
            tmp_path,
            "library_search.pdf",
            "Unique Library Search Paper\nAlice Test\n2026\nAbstract\nThis paper is in the library.",
        )
        folder_upload = post_pdf(client, folder_pdf, folder_id="folder_search")
        library_upload = post_pdf(client, library_pdf)
        assert folder_upload.status_code == 200
        assert library_upload.status_code == 200

        folder_results = client.get("/api/papers/search", params={"keyword": "Unique", "folder_id": "folder_search"}).json()["papers"]
        assert {item["id"] for item in folder_results} == {folder_upload.json()["current_paper"]["paper_id"]}


def test_chat_sessions_store_separate_histories() -> None:
    with TestClient(app) as client:
        session_a = client.post("/api/chat/sessions", json={"title": "对话 A"}).json()["session"]
        session_b = client.post("/api/chat/sessions", json={"title": "对话 B"}).json()["session"]

        first = client.post(
            "/api/chat/message",
            json={"message": "session alpha question", "session_id": session_a["id"], "chat_scope": "global_library"},
        )
        second = client.post(
            "/api/chat/message",
            json={"message": "session beta question", "session_id": session_b["id"], "chat_scope": "global_library"},
        )
        assert first.status_code == 200
        assert second.status_code == 200

        history_a = client.get("/api/chat/history", params={"session_id": session_a["id"]}).json()["messages"]
        history_b = client.get("/api/chat/history", params={"session_id": session_b["id"]}).json()["messages"]
        assert any(item["text"] == "session alpha question" for item in history_a)
        assert not any(item["text"] == "session beta question" for item in history_a)
        assert any(item["text"] == "session beta question" for item in history_b)


def test_create_chat_session() -> None:
    with TestClient(app) as client:
        created = client.post("/api/chat/sessions", json={"title": "新对话"})
        assert created.status_code == 200
        session_id = created.json()["session"]["id"]

        sessions = client.get("/api/chat/sessions")
        assert sessions.status_code == 200
        assert session_id in {session["id"] for session in sessions.json()["sessions"]}


def test_delete_chat_session_removes_history_and_returns_next_session() -> None:
    with TestClient(app) as client:
        session_a = client.post("/api/chat/sessions", json={"title": "待删除对话"}).json()["session"]
        session_b = client.post("/api/chat/sessions", json={"title": "保留对话"}).json()["session"]
        chat = client.post(
            "/api/chat/message",
            json={"message": "delete this session question", "session_id": session_a["id"], "chat_scope": "global_library"},
        )
        assert chat.status_code == 200

        deleted = client.delete(f"/api/chat/sessions/{session_a['id']}")
        assert deleted.status_code == 200
        body = deleted.json()
        assert body["deleted_tasks"] == 1
        assert body["next_session_id"]

        sessions = client.get("/api/chat/sessions").json()["sessions"]
        assert session_a["id"] not in {item["id"] for item in sessions}
        assert session_b["id"] in {item["id"] for item in sessions}

        recreated_history = client.get("/api/chat/history", params={"session_id": session_a["id"]}).json()
        assert recreated_history["messages"] == []
