from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from chat_sessions import create_session, delete_session, ensure_session, get_history, list_sessions, touch_session
from database import init_db
from harness.agent_service import collect_note_image_context, run_chat_graph, run_upload_graph, task_type_from_message
from harness.library_service import delete_paper_response, get_paper_response, list_folders_response, list_papers_response, search_papers_response
from harness.runtime import RuntimeTaskError, run_chat_task, run_upload_task
from llm.codex_diagnostics import codex_health
from llm.model_gateway import get_model_gateway


app = FastAPI(title=config.PROJECT_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    message: str
    current_paper_id: Optional[str] = None
    current_folder_id: Optional[str] = "folder_all"
    session_id: Optional[str] = "session_default"
    chat_scope: str = "paper_and_note"


class ChatSessionCreate(BaseModel):
    title: str = "新对话"


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


def validate_pdf_mime(content_type: str | None) -> None:
    if not content_type:
        return
    normalized = content_type.split(";")[0].strip().lower()
    allowed = {"application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream"}
    if normalized not in allowed:
        raise api_error(400, "invalid_mime_type", "Uploaded file MIME type is not PDF.")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "project": config.PROJECT_NAME,
        "model_execution": get_model_gateway().model_execution_info(),
    }


@app.get("/api/codex/health")
def codex_health_check(run_probes: bool = False) -> dict[str, Any]:
    try:
        return codex_health(run_text=run_probes, run_vision=run_probes)
    except Exception as exc:
        return {
            "codex_found": False,
            "codex_path": "",
            "codex_version": "",
            "llm_provider": config.LLM_PROVIDER,
            "disable_openai_api": config.DISABLE_OPENAI_API,
            "env_openai_api_key_present": False,
            "env_codex_access_token_present": False,
            "codex_home": None,
            "auth_cache_found": False,
            "auth_cache_path": None,
            "auth_cache_top_level_keys": [],
            "text_ok": False,
            "text_error_summary": str(exc)[:500],
            "vision_ok": None,
            "vision_error_summary": "",
            "suspected_auth_mode": "unknown",
            "recommendation": "Codex health diagnostics failed before probing. Check server logs without exposing credentials.",
        }


@app.get("/api/folders")
def list_folders() -> dict[str, Any]:
    return list_folders_response()


@app.get("/api/papers")
def list_papers(folder_id: str = "folder_all") -> dict[str, Any]:
    return list_papers_response(folder_id)


@app.get("/api/papers/search")
def search_papers(keyword: str = "", folder_id: str = "folder_all") -> dict[str, Any]:
    return search_papers_response(keyword, folder_id)


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str) -> dict[str, Any]:
    try:
        return get_paper_response(paper_id)
    except RuntimeTaskError as exc:
        raise api_error(exc.status, exc.code, exc.message) from exc


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str) -> dict[str, Any]:
    try:
        return delete_paper_response(paper_id)
    except RuntimeTaskError as exc:
        raise api_error(exc.status, exc.code, exc.message) from exc


@app.get("/api/chat/sessions")
def list_chat_sessions() -> dict[str, Any]:
    return list_sessions()


@app.post("/api/chat/sessions")
def create_chat_session(payload: ChatSessionCreate) -> dict[str, Any]:
    return create_session(payload.title)


@app.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str) -> dict[str, Any]:
    result = delete_session(session_id)
    if result is None:
        raise api_error(404, "session_not_found", "Chat session not found.")
    return result


@app.get("/api/chat/history")
def chat_history(limit: int = 50, session_id: str = "session_default") -> dict[str, Any]:
    return get_history(limit, session_id)


@app.post("/api/chat/upload")
async def upload_pdf(file: UploadFile = File(...), current_folder_id: str = Form("folder_all"), session_id: str = Form("session_default"), message: str = Form("")) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_UPLOAD_EXTENSIONS:
        raise api_error(400, "invalid_file_type", "Only PDF files are allowed.")
    validate_pdf_mime(file.content_type)
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise api_error(400, "file_too_large", f"PDF exceeds {config.MAX_UPLOAD_MB} MB.")
    if not content.startswith(b"%PDF"):
        raise api_error(400, "invalid_pdf", "Uploaded file does not look like a PDF.")

    try:
        return run_upload_task(
            file_bytes=content,
            file_name=file.filename or "paper.pdf",
            folder_id=current_folder_id,
            session_id=session_id,
            message=message,
            task_type_resolver=task_type_from_message,
            ensure_session_fn=ensure_session,
            touch_session_fn=touch_session,
            upload_graph_runner=run_upload_graph,
        )
    except RuntimeTaskError as exc:
        raise api_error(exc.status, exc.code, exc.message) from exc



@app.post("/api/chat/message")
def chat_message(payload: ChatMessage) -> dict[str, Any]:
    if payload.chat_scope not in {"paper_and_note", "paper_only", "note_only", "global_library"}:
        raise api_error(400, "invalid_chat_scope", "Unsupported chat scope.")
    try:
        return run_chat_task(
            payload=payload,
            task_type_resolver=task_type_from_message,
            ensure_session_fn=ensure_session,
            touch_session_fn=touch_session,
            chat_graph_runner=run_chat_graph,
        )
    except RuntimeTaskError as exc:
        raise api_error(exc.status, exc.code, exc.message) from exc

