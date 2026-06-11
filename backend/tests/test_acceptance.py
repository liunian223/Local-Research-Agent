from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_ROOT = Path(tempfile.mkdtemp(prefix="local_research_agent_tests_"))
os.environ["DATABASE_PATH"] = str(TEST_ROOT / "test.db")
os.environ["DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["PAPER_DIR"] = str(TEST_ROOT / "data" / "papers")
os.environ["PARSED_DIR"] = str(TEST_ROOT / "data" / "parsed")
os.environ["VECTOR_DIR"] = str(TEST_ROOT / "data" / "vector_store")
os.environ["OBSIDIAN_VAULT_PATH"] = str(TEST_ROOT / "vault")
os.environ["VECTOR_BACKEND"] = "local_keyword"
os.environ["DEEPSEEK_API_KEY"] = ""

import fitz
from fastapi.testclient import TestClient
from langgraph.graph import StateGraph

from app import app
from graph.builder import build_langgraph_app


def make_pdf(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    doc = fitz.open()
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

        delete_all = client.delete("/api/folders/folder_all")
        assert delete_all.status_code == 400
        assert delete_all.json()["detail"]["error"]["code"] == "cannot_delete_system_folder"


def test_folder_lifecycle_and_non_empty_delete_rejected(tmp_path: Path) -> None:
    with TestClient(app) as client:
        folder = client.post("/api/folders", json={"name": "AcceptanceFolder"}).json()["folder"]
        assert client.delete(f"/api/folders/{folder['id']}").status_code == 200

        folder = client.post("/api/folders", json={"name": "NonEmptyFolder"}).json()["folder"]
        pdf = make_pdf(
            tmp_path,
            "non_empty_folder.pdf",
            "Non Empty Folder Paper\nAlice Test\n2026\nAbstract\nThis paper proves non empty folder deletion is rejected.",
        )
        upload = post_pdf(client, pdf, folder_id=folder["id"])
        assert upload.status_code == 200

        rejected = client.delete(f"/api/folders/{folder['id']}")
        assert rejected.status_code == 400
        assert rejected.json()["detail"]["error"]["code"] == "folder_not_empty"


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
        assert body["message_type"] == "note_generated"

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
