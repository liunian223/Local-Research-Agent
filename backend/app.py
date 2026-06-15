from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from agents.knowledge_rag_agent import knowledge_rag_agent_node
from agents.note_skill_agent import note_skill_agent_node
from chat_sessions import create_session, delete_session, ensure_session, get_history, list_sessions, touch_session
from deepseek_client import build_note_generation_prompt_text, build_rag_answer_prompt_text
from database import connect, init_db, log_a2a, log_mcp, log_trace, new_id, now_iso, row_to_dict, rows_to_dicts
from graph.builder import initial_phase, run_graph
from graph.state import AgentState
from harness.context_manager import context_pack_strategy
from harness.runtime import RuntimeTaskError, run_chat_task, run_upload_task
from layout_parser import parse_pdf_layout, save_layout_artifacts
from llm.model_gateway import get_model_gateway
from mcp_servers.database_mcp_server import delete_paper_artifacts, insert_chunks, insert_note, insert_note_chunks, insert_paper, update_paper_status
from mcp_servers.file_mcp_server import copy_pdf_to_obsidian, read_pdf_text, save_uploaded_pdf, write_markdown_note
from note_skill import check_required_note_sections, quality_json, run_deep_paper_note_skill, safe_obsidian_attachment_path, safe_obsidian_path
from pdf_tools import extract_metadata, safe_filename, sha256_bytes
from rag import note_to_chunks, split_chunks
from semantic_chunker import build_semantic_chunks
from structured_retriever import build_evidence_bundle, collect_structured_scope_chunks, retrieve_structured_evidence
from tool_gateway import ToolGateway
from vector_store import VECTOR_STORE


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


@app.get("/api/folders")
def list_folders() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name, is_system, created_at, updated_at FROM folders ORDER BY is_system DESC, created_at ASC").fetchall()
    folders = rows_to_dicts(rows)
    for folder in folders:
        folder["is_system"] = bool(folder["is_system"])
    return {"folders": folders}


def paper_dict(row: Any) -> dict[str, Any]:
    paper = row_to_dict(row) or {}
    return paper


def papers_with_notes(conn: Any, rows: list[Any]) -> list[dict[str, Any]]:
    papers = rows_to_dicts(rows)
    for paper in papers:
        note = conn.execute(
            "SELECT id, obsidian_path, created_at, updated_at FROM reading_notes WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1",
            (paper["id"],),
        ).fetchone()
        paper["latest_note"] = row_to_dict(note)
    return papers


@app.get("/api/papers")
def list_papers(folder_id: str = "folder_all") -> dict[str, Any]:
    with connect() as conn:
        if folder_id == "folder_all":
            rows = conn.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM papers WHERE folder_id = ? ORDER BY created_at DESC", (folder_id,)).fetchall()
        papers = papers_with_notes(conn, rows)
    return {"papers": papers}


@app.get("/api/papers/search")
def search_papers(keyword: str = "", folder_id: str = "folder_all") -> dict[str, Any]:
    like = f"%{keyword.strip()}%"
    with connect() as conn:
        if folder_id == "folder_all":
            rows = conn.execute(
                "SELECT * FROM papers WHERE title LIKE ? OR authors LIKE ? ORDER BY created_at DESC",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM papers WHERE folder_id = ? AND (title LIKE ? OR authors LIKE ?) ORDER BY created_at DESC",
                (folder_id, like, like),
            ).fetchall()
        papers = papers_with_notes(conn, rows)
    return {"papers": papers}


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str) -> dict[str, Any]:
    with connect() as conn:
        paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not paper:
            raise api_error(404, "paper_not_found", "Paper not found.")
        note = conn.execute("SELECT * FROM reading_notes WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1", (paper_id,)).fetchone()
    return {"paper": paper_dict(paper), "note": row_to_dict(note)}


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str) -> dict[str, Any]:
    with connect() as conn:
        paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not paper:
            raise api_error(404, "paper_not_found", "Paper not found.")
        vector_cleanup: list[dict[str, Any]] = []
        deleted_papers = delete_papers(conn, [paper_dict(paper)], vector_cleanup)
    return {"status": "deleted", "deleted_papers": deleted_papers, "vector_cleanup": vector_cleanup}


def safe_unlink(path: str | Path | None, roots: list[Path]) -> bool:
    if not path:
        return False
    try:
        target = Path(path).resolve()
        if not any(target.is_relative_to(root.resolve()) for root in roots):
            return False
        if target.is_file():
            target.unlink()
            return True
    except OSError:
        return False
    return False


def cleanup_paths_for_paper(paper: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    paper_id = paper.get("id")
    file_path = paper.get("file_path")
    note_path = paper.get("obsidian_note_path")
    if file_path:
        paths.append(Path(file_path))
        paths.append(safe_obsidian_attachment_path(Path(file_path).name))
    if paper_id:
        paths.append(config.PARSED_DIR / f"{paper_id}.txt")
    if note_path:
        paths.append(Path(note_path))
    return paths


def delete_papers(conn: Any, papers: list[dict[str, Any]], vector_cleanup_results: list[dict[str, Any]] | None = None) -> int:
    if not papers:
        return 0
    paper_ids = [paper["id"] for paper in papers]
    placeholders = ",".join("?" for _ in paper_ids)
    roots = [config.PAPER_DIR, config.PARSED_DIR, config.OBSIDIAN_VAULT_PATH]
    note_ids = [
        row["id"]
        for row in conn.execute(f"SELECT id FROM reading_notes WHERE paper_id IN ({placeholders})", paper_ids).fetchall()
    ]
    for paper in papers:
        try:
            result = VECTOR_STORE.delete_by_paper_id(paper["id"])
        except Exception as exc:
            result = {"backend": getattr(VECTOR_STORE, "backend", "unknown"), "status": "failed", "paper_id": paper["id"], "error": str(exc)[:300]}
        if vector_cleanup_results is not None:
            vector_cleanup_results.append({"target": "paper", "id": paper["id"], **result})
    for note_id in note_ids:
        try:
            result = VECTOR_STORE.delete_by_note_id(note_id)
        except Exception as exc:
            result = {"backend": getattr(VECTOR_STORE, "backend", "unknown"), "status": "failed", "note_id": note_id, "error": str(exc)[:300]}
        if vector_cleanup_results is not None:
            vector_cleanup_results.append({"target": "note", "id": note_id, **result})
    for paper in papers:
        for path in cleanup_paths_for_paper(paper):
            safe_unlink(path, roots)
    delete_paper_artifacts(conn, paper_ids)
    return len(paper_ids)


def collect_scope_chunks(conn: Any, scope: str, paper_id: str | None) -> list[dict[str, Any]]:
    return collect_structured_scope_chunks(conn, scope, paper_id)


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


def has_partial_note_fallback(fallbacks: list[Any]) -> bool:
    return any(
        (isinstance(item, dict) and item.get("type") in {"partial_note_fallback", "long_paper_staged_generation"})
        or item in {"partial_note_fallback", "long_paper_staged_generation"}
        for item in fallbacks
    )


def remove_local_note_generation_fallbacks(fallbacks: list[Any]) -> list[Any]:
    local_note_fallbacks = {
        "partial_note_fallback",
        "long_paper_staged_generation",
    }
    return [
        item
        for item in fallbacks
        if not (
            (isinstance(item, dict) and item.get("type") in local_note_fallbacks)
            or item in local_note_fallbacks
        )
    ]


def task_type_from_message(message: str, has_upload: bool = False) -> str:
    lowered = message.lower()
    wants_note_after_upload = any(token in lowered for token in ["生成笔记", "阅读笔记", "笔记", "obsidian", "note"])
    wants_generate_note = any(
        token in lowered
        for token in [
            "生成笔记",
            "阅读笔记",
            "生成 obsidian",
            "obsidian 阅读笔记",
            "generate note",
            "create note",
            "write note",
        ]
    )
    if has_upload and wants_note_after_upload:
        return "import_and_note"
    if has_upload:
        return "import_paper"
    if wants_generate_note:
        return "generate_note"
    return "global_chat" if "全知识库" in message else "paper_chat"


def retrieve_evidence(gateway: ToolGateway, conn: Any, scope: str, paper_id: str | None, query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return gateway.invoke(
        "Knowledge RAG Agent",
        "rag",
        "adaptive_retrieve" if config.RAG_ADAPTIVE_ENABLED else "retrieve_structured_evidence",
        retrieve_structured_evidence,
        conn,
        scope,
        paper_id,
        query,
        input_summary=f"scope={scope}; paper_id={paper_id or ''}",
        output_summarizer=lambda value: f"{len(value[0])} evidence chunks returned by {value[1].get('backend')}; mode={value[1].get('retrieval_mode')}",
    )


def synthesize_answer_with_optional_llm(gateway: ToolGateway, task_id: str, question: str, evidence: list[dict[str, Any]], fallbacks: list[str]) -> str:
    if not evidence:
        fallbacks.append("no_matching_evidence")
        return "没有检索到可引用的 evidence。请先确认 PDF 已成功解析并完成索引，或换一个更具体的问题再试。"

    model_gateway = get_model_gateway()
    system, prompt = build_rag_answer_prompt_text(question, evidence)
    result = model_gateway.generate_text(
        prompt,
        system=system,
        purpose="chat",
        temperature=0.2,
        max_output_tokens=1600,
    )
    if result.ok:
        log_mcp(gateway.conn, task_id, "llm", "model_chat", result.model, result.usage_summary or "Model answer generated.")
        return result.content

    fallbacks.append("model_chat_failed_local_rag_answer_used")
    log_mcp(gateway.conn, task_id, "llm", "model_chat", result.model, "Model call failed.", status="error", error=result.error)
    bullets = "\n".join(f"- {item['section_name']}: {item['text'][:220]}" for item in evidence[:3])
    return f"模型调用失败，已使用本地 RAG 兜底回答：\n{bullets}"


def collect_note_image_context(conn: Any, paper_id: str, evidence: list[dict[str, Any]], limit: int | None = None) -> tuple[list[str], str]:
    limit = limit or config.MAX_NOTE_IMAGE_ATTACHMENTS
    selected: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_item(path: str, label: str, caption: str = "", page: Any = None, source: str = "") -> None:
        if not path:
            return
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = config.ROOT_DIR / resolved
        if not resolved.exists() or not resolved.is_file():
            return
        key = str(resolved.resolve()).lower()
        if key in seen_paths:
            return
        seen_paths.add(key)
        selected.append(
            {
                "path": str(resolved),
                "label": label,
                "caption": caption,
                "page": page,
                "source": source,
            }
        )

    for item in evidence:
        metadata = item.get("metadata") or {}
        figure = metadata.get("figure") if isinstance(metadata.get("figure"), dict) else {}
        figure_ids = metadata.get("figure_ids") or []
        figure_label = figure.get("figure_id") or (figure_ids[0] if figure_ids else "figure")
        add_item(
            metadata.get("image_path") or figure.get("image_path") or "",
            label=figure_label,
            caption=figure.get("caption") or item.get("section_name") or "",
            page=item.get("page_start") or figure.get("page_number"),
            source="retrieved_figure",
        )
        add_item(
            metadata.get("page_image_path") or figure.get("page_image_path") or "",
            label=f"page_{item.get('page_start') or figure.get('page_number') or ''}",
            caption=figure.get("caption") or item.get("section_name") or "",
            page=item.get("page_start") or figure.get("page_number"),
            source="retrieved_page",
        )
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        rows = conn.execute(
            """
            SELECT * FROM document_figures
            WHERE paper_id = ? AND COALESCE(image_path, '') <> ''
            ORDER BY page_number ASC, id ASC
            LIMIT ?
            """,
            (paper_id, limit * 2),
        ).fetchall()
        for row in rows_to_dicts(rows):
            metadata = json.loads(row.get("metadata_json") or "{}")
            add_item(row.get("image_path") or "", row.get("id") or "figure", row.get("caption") or "", row.get("page_number"), "paper_figure")
            add_item(metadata.get("page_image_path") or "", f"page_{row.get('page_number')}", row.get("caption") or "", row.get("page_number"), "paper_page")
            if len(selected) >= limit:
                break

    image_paths = [item["path"] for item in selected[:limit]]
    if not selected:
        return [], ""
    lines = [
        f"- [{idx}] {item['label']} page={item.get('page') or ''} source={item['source']} caption={item['caption']} path={item['path']}"
        for idx, item in enumerate(selected[:limit], start=1)
    ]
    return image_paths, "Multimodal image attachments available to the model:\n" + "\n".join(lines)


def ingest_pdf(conn: Any, gateway: ToolGateway, task_id: str, file_bytes: bytes, original_name: str, folder_id: str) -> tuple[dict[str, Any], list[str]]:
    fallbacks: list[str] = []
    file_hash = sha256_bytes(file_bytes)
    existing = conn.execute("SELECT * FROM papers WHERE file_sha256 = ?", (file_hash,)).fetchone()
    if existing:
        log_mcp(conn, task_id, "database", "find_existing_paper", original_name, "Duplicate PDF returned existing paper.")
        return paper_dict(existing), ["duplicate_pdf_returned_existing_paper"]

    paper_id = new_id("paper")
    filename = f"{paper_id}_{safe_filename(original_name)}.pdf"
    target = (config.PAPER_DIR / filename).resolve()
    if not str(target).startswith(str(config.PAPER_DIR.resolve())):
        raise api_error(400, "invalid_path", "Upload path escapes paper directory.")
    gateway.invoke(
        "Knowledge RAG Agent",
        "file",
        "save_uploaded_pdf",
        save_uploaded_pdf,
        target,
        file_bytes,
        input_summary=original_name,
        output_summarizer=lambda value: str(target),
    )

    parsed = gateway.invoke(
        "Knowledge RAG Agent",
        "file",
        "read_pdf_text",
        read_pdf_text,
        target,
        input_summary=str(target),
        output_summarizer=lambda value: f"parser={value['parser']}; chars={len(value['text'])}; pages={value['page_count']}",
    )
    if parsed["parser"] == "failed":
        parse_status = "failed"
        fallbacks.append("pdf_text_parse_failed_but_paper_was_imported")
    elif len(parsed["text"]) < 1000:
        parse_status = "partial"
        fallbacks.append("pdf_text_parse_partial")
    else:
        parse_status = "done"
    metadata = extract_metadata(target, parsed["text"], parsed["page_count"])
    if metadata.get("metadata_warning"):
        fallbacks.append("metadata_fallback_used")

    parsed_path = config.PARSED_DIR / f"{paper_id}.txt"
    gateway.invoke(
        "Knowledge RAG Agent",
        "file",
        "write_parsed_text",
        parsed_path.write_text,
        parsed["text"],
        encoding="utf-8",
        input_summary=f"{paper_id}; chars={len(parsed['text'])}",
        output_summarizer=lambda value: str(parsed_path),
    )
    now = now_iso()
    paper = {
        "id": paper_id,
        "title": metadata["title"],
        "authors": metadata["authors"],
        "year": metadata["year"],
        "language": metadata["language"],
        "doi": metadata["doi"],
        "file_path": str(target),
        "file_name": original_name,
        "file_sha256": file_hash,
        "page_count": metadata["page_count"],
        "folder_id": folder_id or "folder_all",
        "parse_status": parse_status,
        "vector_status": "skipped",
        "note_status": "none",
        "obsidian_note_path": "",
        "metadata_source": metadata["metadata_source"],
        "metadata_confidence": metadata["metadata_confidence"],
        "metadata_warning": metadata["metadata_warning"],
        "parse_warning": "; ".join(parsed["warnings"])[:1200],
        "created_at": now,
        "updated_at": now,
    }
    gateway.invoke(
        "Knowledge RAG Agent",
        "database",
        "insert_paper",
        insert_paper,
        conn,
        paper,
        input_summary=f"paper_id={paper_id}; title={paper['title']}",
        output_summarizer=lambda value: f"title={value['title']}; parse_status={value['parse_status']}",
    )

    document = gateway.invoke(
        "Knowledge RAG Agent",
        "rag",
        "parse_layout_document",
        parse_pdf_layout,
        target,
        paper,
        parsed["text"],
        input_summary=f"paper_id={paper_id}; parser={parsed['parser']}",
        output_summarizer=lambda value: f"pages={len(value.get('pages', []))}; sections={len(value.get('sections', []))}; tables={len(value.get('tables', []))}; figures={len(value.get('figures', []))}",
    )
    chunks = build_semantic_chunks(document, paper) if parsed["text"] or document.get("text_blocks") else []
    save_layout_artifacts(document)
    (config.PARSED_DIR / paper_id / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    gateway.invoke(
        "Knowledge RAG Agent",
        "database",
        "insert_chunks",
        insert_chunks,
        conn,
        document,
        chunks,
        input_summary=f"paper_id={paper_id}; chunks={len(chunks)}",
        output_summarizer=lambda value: f"pages={value['pages']}; sections={value['sections']}; chunks={value['chunks']}",
    )
    vector_status = "done" if chunks else "skipped"
    index_result = gateway.invoke(
        "Knowledge RAG Agent",
        "rag",
        "build_vector_index",
        VECTOR_STORE.index_chunks,
        chunks,
        "paper",
        paper_id,
        input_summary=f"paper_id={paper_id}; chunks={len(chunks)}",
        output_summarizer=lambda value: f"backend={value['backend']}; indexed={value['indexed']}; status={value['status']}",
    )
    if index_result.get("status") == "fallback_index_recorded":
        vector_status = "done"
    conn.execute("UPDATE papers SET vector_status = ?, updated_at = ? WHERE id = ?", (vector_status, now_iso(), paper_id))
    paper["vector_status"] = vector_status
    return paper, fallbacks


def generate_note(
    conn: Any,
    gateway: ToolGateway,
    task_id: str,
    paper: dict[str, Any],
    query: str,
    evidence: list[dict[str, Any]] | None = None,
    retrieve_meta: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any]]:
    if evidence is None or retrieve_meta is None:
        evidence, retrieve_meta = retrieve_evidence(gateway, conn, "paper_only", paper["id"], query or paper.get("title", ""))
    evidence_bundle = build_evidence_bundle(evidence or [], retrieve_meta or {})
    rows = collect_scope_chunks(conn, "paper_only", paper["id"])
    if not evidence and rows:
        evidence = [{**row, "rank": idx + 1, "score": 0, "text": row.get("text", "")[: config.MAX_EVIDENCE_CHARS]} for idx, row in enumerate(rows[:5])]
        evidence_bundle = build_evidence_bundle(evidence, retrieve_meta or {})
    full_text = "\n\n".join(row.get("text", "") for row in rows)
    skill_result = gateway.invoke(
        "Note Skill Agent",
        "skills",
        "run_deep_paper_note_skill",
        run_deep_paper_note_skill,
        paper,
        evidence_bundle,
        full_text,
        evidence,
        "zh",
        {"note_mode": "long_paper" if len(full_text) > config.LONG_PAPER_CHAR_THRESHOLD or len(evidence) > config.LONG_PAPER_CHUNK_THRESHOLD else "normal", "template_version": "obsidian_note_v2", "max_repair_rounds": config.MAX_NOTE_REPAIR_ROUNDS},
        input_summary=f"paper_id={paper['id']}; evidence={len(evidence)}; text_chars={len(full_text)}",
        output_summarizer=lambda value: f"status={value['status']}; markdown_chars={len(value['note_markdown'])}; phases={len(value['skill_phases'])}",
    )
    markdown = skill_result["note_markdown"]
    quality = skill_result["quality_check"]
    phases = skill_result["skill_phases"]
    fallbacks: list[Any] = list(skill_result.get("fallbacks", []))
    model_gateway = get_model_gateway()
    system, prompt = build_note_generation_prompt_text(paper, evidence, full_text)
    prompt = f"{prompt}\n\nStructured evidence bundle:\n{format_grouped_evidence_for_prompt(evidence_bundle)}\n\nRules: abstract_chunks are high-level clues only. Prefer body method/experiment/result evidence for concrete claims. If body evidence is insufficient, say so."
    image_paths, image_context = collect_note_image_context(conn, paper["id"], evidence)
    if image_context:
        prompt = f"{prompt}\n\n{image_context}\n\n请结合这些图片附件和文本 evidence 生成笔记；涉及图中信息时注明来自图像/图注/附近文本的证据。"
        phases.append({"name": "multimodal_evidence", "status": "success", "summary": f"Attached {len(image_paths)} figure/page images for model note generation."})
    else:
        phases.append({"name": "multimodal_evidence", "status": "skipped", "summary": "No extracted figure/page images available for model note generation."})
    llm_result = model_gateway.generate_text(
        prompt,
        system=system,
        purpose="note",
        temperature=0.2,
        max_output_tokens=3600,
        image_paths=image_paths,
    )
    if llm_result.ok:
        llm_quality = check_required_note_sections(llm_result.content)
        log_mcp(
            conn,
            task_id,
            "llm",
            "model_note_generation",
            f"{llm_result.model}; images={len(image_paths)}",
            llm_result.usage_summary or f"Model note generated; images={len(image_paths)}",
        )
        if llm_quality["ok"]:
            markdown = llm_result.content
            fallbacks = remove_local_note_generation_fallbacks(fallbacks)
            quality = {
                **quality,
                **llm_quality,
                "llm_generated": True,
                "model": llm_result.model,
                "usage_summary": llm_result.usage_summary,
                "multimodal_image_count": len(image_paths),
            }
            phases.append({"name": "llm_note_generation", "status": "ok", "summary": f"Generated note with {llm_result.model}."})
        else:
            fallbacks.append("model_note_missing_required_sections_local_note_used")
            quality = {**quality, "llm_generated": False, "llm_quality": llm_quality}
            phases.append({"name": "repair_if_needed", "status": "fallback", "summary": "Model note missed required headings; kept local structured note."})
    else:
        fallbacks.append("model_note_generation_failed_local_note_used")
        log_mcp(conn, task_id, "llm", "model_note_generation", f"{llm_result.model}; images={len(image_paths)}", "Model note generation failed.", status="error", error=llm_result.error)
        phases.append({"name": "llm_note_generation", "status": "fallback", "summary": "Model call failed; used local note template."})
    folder = None
    if paper.get("folder_id") and paper["folder_id"] != "folder_all":
        folder = conn.execute("SELECT name FROM folders WHERE id = ?", (paper["folder_id"],)).fetchone()
    note_path = safe_obsidian_path(paper.get("title") or paper["id"], folder["name"] if folder else None)
    gateway.invoke(
        "Note Skill Agent",
        "file",
        "write_markdown_note",
        write_markdown_note,
        note_path,
        markdown,
        input_summary=paper.get("title", ""),
        output_summarizer=lambda value: str(note_path),
    )
    attachment_path = safe_obsidian_attachment_path(Path(paper.get("file_path") or paper.get("file_name") or f"{paper['id']}.pdf").name)
    gateway.invoke(
        "Note Skill Agent",
        "file",
        "copy_pdf_to_obsidian",
        copy_pdf_to_obsidian,
        Path(paper["file_path"]),
        attachment_path,
        input_summary=f"paper_id={paper['id']}",
        output_summarizer=lambda value: str(attachment_path),
    )

    note_id = new_id("note")
    gateway.invoke(
        "Note Skill Agent",
        "database",
        "insert_note",
        insert_note,
        conn,
        {
            "id": note_id,
            "paper_id": paper["id"],
            "content_markdown": markdown,
            "obsidian_path": str(note_path),
            "quality_check_json": quality_json(quality),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        },
        input_summary=f"paper_id={paper['id']}; note_id={note_id}",
        output_summarizer=lambda value: value["id"],
    )
    note_chunks = note_to_chunks(note_id, paper["id"], markdown)
    gateway.invoke(
        "Note Skill Agent",
        "database",
        "insert_note_chunks",
        insert_note_chunks,
        conn,
        note_chunks,
        input_summary=f"note_id={note_id}; chunks={len(note_chunks)}",
        output_summarizer=lambda value: f"chunks={value}",
    )
    for chunk in note_chunks:
        chunk.update(
            {
                "source_type": "note",
                "note_id": note_id,
                "paper_id": paper["id"],
            }
        )
    note_index_result = gateway.invoke(
        "Note Skill Agent",
        "rag",
        "build_note_vector_index",
        VECTOR_STORE.index_chunks,
        note_chunks,
        "note",
        paper["id"],
        note_id,
        input_summary=f"note_id={note_id}; chunks={len(note_chunks)}",
        output_summarizer=lambda value: f"backend={value['backend']}; indexed={value['indexed']}; status={value['status']}",
    )
    note_status = "done" if skill_result.get("status") == "success" else "partial"
    gateway.invoke(
        "Note Skill Agent",
        "database",
        "update_paper_status",
        update_paper_status,
        conn,
        paper["id"],
        note_status,
        str(note_path),
        input_summary=f"paper_id={paper['id']}; note_status={note_status}",
        output_summarizer=lambda value: note_status,
    )
    paper["note_status"] = note_status
    paper["obsidian_note_path"] = str(note_path)
    paper["obsidian_pdf_path"] = str(attachment_path)
    phases.extend(
        [
            {"name": "write_obsidian_note", "status": "success", "summary": str(note_path)},
            {"name": "copy_pdf_to_obsidian", "status": "success", "summary": str(attachment_path)},
            {"name": "insert_note", "status": "success", "summary": note_id},
            {"name": "insert_note_chunks", "status": "success", "summary": f"chunks={len(note_chunks)}"},
            {"name": "build_note_vector_index", "status": "success" if note_index_result.get("status") in {"done", "fallback_index_recorded"} else "partial", "summary": f"backend={note_index_result.get('backend')}; status={note_index_result.get('status')}"},
        ]
    )
    note_generation = {
        "mode": quality.get("note_generation_mode") or ("long_paper" if quality.get("long_paper") else "normal"),
        "template_version": quality.get("template_version") or "obsidian_note_v2",
        "quality_check": quality,
        "repair_rounds": quality.get("repair_rounds", 0),
        "repair_log": quality.get("repair_log", []),
        "note_id": note_id,
        "note_chunks": len(note_chunks),
        "note_vector_status": note_index_result.get("status", "unknown"),
        "vector_backend": note_index_result.get("backend", ""),
        "markdown_path": str(note_path),
        "pdf_attachment_path": str(attachment_path),
        "evidence_group_counts": quality.get("evidence_group_counts", {}),
    }
    return markdown, quality, phases, evidence, fallbacks, note_generation


def format_grouped_evidence_for_prompt(evidence_bundle: dict[str, Any]) -> str:
    labels = [
        ("section_summaries", "Section Summaries"),
        ("text_chunks", "Text Chunks"),
        ("abstract_chunks", "Abstract Clues"),
        ("tables", "Tables"),
        ("figures", "Figures"),
        ("pages", "Pages"),
    ]
    parts: list[str] = []
    for key, label in labels:
        items = evidence_bundle.get(key) or []
        if not items:
            continue
        lines = []
        for item in items[:6]:
            location = item.get("section_path") or item.get("section_name") or key
            text = (item.get("text") or "")[: config.MAX_EVIDENCE_CHARS]
            lines.append(f"- [{location}] {text}")
        parts.append(f"[{label}]\n" + "\n".join(lines))
    return "\n\n".join(parts) or "No grouped evidence available."


def synthesize_answer_from_bundle_with_optional_llm(
    gateway: ToolGateway,
    task_id: str,
    question: str,
    evidence: list[dict[str, Any]],
    evidence_bundle: dict[str, Any],
    retrieval: dict[str, Any],
    chat_scope: str,
    fallbacks: list[str],
) -> str:
    if not evidence:
        fallbacks.append("no_matching_evidence")
        return "没有检索到足够的 evidence。当前回答可靠性较低，建议重新上传更完整的 PDF 或换一个更具体的问题。"
    model_gateway = get_model_gateway()
    grouped = format_grouped_evidence_for_prompt(evidence_bundle)
    query_analysis = retrieval.get("query_analysis") or {}
    coverage = retrieval.get("coverage_check") or {}
    system = (
        "You are the Note Skill Agent in Local Research Agent. Answer in Chinese. "
        "Use only the grouped local evidence. If evidence is insufficient, say so clearly. "
        "Abstract evidence is only a high-level clue unless the user explicitly asks for abstract or whole-paper summary."
    )
    prompt = f"""[Question]
{question}

[Chat Scope]
{chat_scope}

[Query Analysis]
complexity: {query_analysis.get('complexity', '')}
intent: {query_analysis.get('intent', '')}
abstract_mode: {query_analysis.get('abstract_mode', '')}

{grouped}

[Coverage]
{json.dumps(coverage, ensure_ascii=False)}

[Rules]
1. Do not use abstract evidence as a substitute for method, experiment, result, or limitation body evidence.
2. For complex questions, separate directly supported conclusions from reasonable evidence-based inference.
3. If coverage is insufficient, state which part lacks evidence.
4. Keep the answer concise, structured, and grounded.
"""
    result = model_gateway.generate_text(prompt, system=system, purpose="chat", temperature=0.2, max_output_tokens=1600)
    if result.ok:
        log_mcp(gateway.conn, task_id, "llm", "model_chat", result.model, result.usage_summary or "Grouped evidence answer generated.")
        return result.content
    fallbacks.append("model_chat_failed_local_rag_answer_used")
    log_mcp(gateway.conn, task_id, "llm", "model_chat", result.model, "Model call failed.", status="error", error=result.error)
    bullets = "\n".join(f"- {item.get('section_name', '')}: {(item.get('text') or '')[:220]}" for item in evidence[:3])
    return f"模型调用失败，已使用本地 grouped evidence 兜底回答：\n{bullets}"


def run_upload_graph(conn: Any, task_id: str, task_type: str, file_bytes: bytes, file_name: str, folder_id: str, message: str) -> AgentState:
    gateway = ToolGateway(conn, task_id)
    step = {"value": 1}

    def trace(node: str, agent: str, action: str, summary: str) -> None:
        log_trace(conn, task_id, step["value"], node, agent, action, summary)
        step["value"] += 1

    trace("coordinator_node", "Harness", "route_task", f"task_type={task_type}; phase={initial_phase(task_type)}")
    state: AgentState = {
        "task_id": task_id,
        "run_id": new_id("run"),
        "user_input": message,
        "task_type": task_type,
        "phase": "START",
        "current_folder_id": folder_id,
        "chat_scope": "paper_and_note",
        "context_pack_strategy": context_pack_strategy(task_type, "paper_and_note"),
        "harness": {"runtime_status": "running"},
        "uploaded_file_bytes": file_bytes,
        "original_file_name": file_name,
        "fallbacks": [],
        "skill_phases": [],
        "rag_evidence": [],
        "artifacts": {},
        "status": "running",
    }

    def import_handler(inner: AgentState) -> AgentState:
        trace("knowledge_rag_agent_node", "Knowledge RAG Agent", "import_paper", "phase=IMPORT_PAPER")
        paper, fallbacks = ingest_pdf(conn, gateway, task_id, file_bytes, file_name, folder_id)
        inner["paper"] = paper
        inner["current_paper_id"] = paper["id"]
        inner["import_done"] = True
        inner.setdefault("fallbacks", []).extend(fallbacks)
        inner["artifacts"] = {
            "markdown_path": paper.get("obsidian_note_path", ""),
            "pdf_path": paper["file_path"],
            "obsidian_pdf_path": paper.get("obsidian_pdf_path", ""),
        }
        log_a2a(conn, task_id, "Knowledge RAG Agent", "Note Skill Agent", "paper_imported", {"paper_id": paper["id"], "title": paper["title"]})
        if task_type == "import_and_note":
            inner["phase"] = "REQUEST_EVIDENCE"
            inner["needs_evidence"] = True
        else:
            inner["phase"] = "IMPORT_DONE"
            inner["answer"] = f"已接收 PDF《{paper['title']}》，解析状态：{paper['parse_status']}，索引状态：{paper['vector_status']}。"
            inner["message_type"] = "paper_imported"
        return inner

    def retrieve_handler(inner: AgentState) -> AgentState:
        trace("knowledge_rag_agent_node", "Knowledge RAG Agent", "retrieve_evidence", "phase=REQUEST_EVIDENCE")
        paper = inner.get("paper") or {}
        evidence, retrieve_meta = retrieve_evidence(gateway, conn, "paper_only", paper.get("id"), message or paper.get("title", ""))
        inner["retrieved_chunks"] = evidence
        inner["rag_evidence"] = evidence
        inner["retrieve_meta"] = retrieve_meta
        inner["retrieval"] = retrieve_meta
        inner["evidence_bundle"] = build_evidence_bundle(evidence, retrieve_meta)
        inner["evidence_ready"] = True
        inner["needs_evidence"] = False
        inner["phase"] = "EVIDENCE_READY"
        if not evidence:
            inner.setdefault("fallbacks", []).append("no_relevant_evidence_for_note")
        log_a2a(conn, task_id, "Knowledge RAG Agent", "Note Skill Agent", "evidence_bundle_ready", {"count": len(evidence), "scope": "paper_only", "evidence_bundle": inner["evidence_bundle"]})
        return inner

    def note_handler(inner: AgentState) -> AgentState:
        trace("note_skill_agent_node", "Note Skill Agent", "generate_note", "phase=EVIDENCE_READY")
        paper = inner.get("paper") or {}
        _, quality, phases, evidence, note_fallbacks, note_generation = generate_note(
            conn,
            gateway,
            task_id,
            paper,
            message,
            inner.get("rag_evidence", []),
            inner.get("retrieve_meta") or inner.get("retrieval") or {},
        )
        inner["paper"] = paper
        inner["note_quality_check"] = quality
        inner["note_generation"] = note_generation
        inner["note_id"] = note_generation.get("note_id")
        inner["note_vector_status"] = note_generation.get("note_vector_status", "")
        inner["obsidian_note_path"] = note_generation.get("markdown_path", "")
        inner["obsidian_pdf_path"] = note_generation.get("pdf_attachment_path", "")
        inner["skill_phases"] = phases
        inner["rag_evidence"] = evidence
        inner.setdefault("fallbacks", []).extend(note_fallbacks)
        inner["note_ready"] = True
        inner["phase"] = "NOTE_READY"
        if has_partial_note_fallback(inner.get("fallbacks", [])):
            inner["answer"] = f"已导入 PDF《{paper['title']}》，并生成降级版 Obsidian 阅读笔记，部分章节可能需要人工补充。"
        else:
            inner["answer"] = f"已导入 PDF《{paper['title']}》，并生成 Obsidian Markdown 阅读笔记。"
        inner["message_type"] = "note_generated"
        inner["artifacts"] = {
            "markdown_path": paper.get("obsidian_note_path", ""),
            "pdf_path": paper["file_path"],
            "obsidian_pdf_path": paper.get("obsidian_pdf_path", ""),
        }
        return inner

    def answer_handler(inner: AgentState) -> AgentState:
        inner["phase"] = "ERROR"
        inner["error"] = "Upload graph should not answer chat."
        return inner

    final_state = run_graph(
        state,
        lambda inner: knowledge_rag_agent_node(inner, import_handler, retrieve_handler),
        lambda inner: note_skill_agent_node(inner, note_handler, answer_handler),
    )
    trace("finish_node", "Harness", "finish", f"phase={final_state.get('phase')}; status={final_state.get('status')}")
    return final_state


def run_chat_graph(conn: Any, task_id: str, payload: ChatMessage, paper: dict[str, Any] | None) -> AgentState:
    gateway = ToolGateway(conn, task_id)
    step = {"value": 1}
    task_type = task_type_from_message(payload.message)

    def trace(node: str, agent: str, action: str, summary: str) -> None:
        log_trace(conn, task_id, step["value"], node, agent, action, summary)
        step["value"] += 1

    trace("coordinator_node", "Harness", "route_task", f"task_type={task_type}; phase={initial_phase(task_type)}")
    state: AgentState = {
        "task_id": task_id,
        "run_id": new_id("run"),
        "user_input": payload.message,
        "task_type": task_type,
        "phase": "START",
        "current_paper_id": payload.current_paper_id,
        "current_folder_id": payload.current_folder_id,
        "chat_scope": payload.chat_scope,
        "context_pack_strategy": context_pack_strategy(task_type, payload.chat_scope),
        "harness": {"runtime_status": "running"},
        "paper": paper or {},
        "fallbacks": [],
        "skill_phases": [],
        "rag_evidence": [],
        "artifacts": {"markdown_path": paper.get("obsidian_note_path", "") if paper else "", "pdf_path": paper.get("file_path", "") if paper else ""},
        "status": "running",
    }

    def import_handler(inner: AgentState) -> AgentState:
        inner["phase"] = "ERROR"
        inner["error"] = "Chat graph should not import paper."
        return inner

    def retrieve_handler(inner: AgentState) -> AgentState:
        trace("knowledge_rag_agent_node", "Knowledge RAG Agent", "retrieve_evidence", f"scope={payload.chat_scope}")
        evidence, retrieve_meta = retrieve_evidence(gateway, conn, payload.chat_scope, payload.current_paper_id, payload.message)
        inner["retrieved_chunks"] = evidence
        inner["rag_evidence"] = evidence
        inner["retrieve_meta"] = retrieve_meta
        inner["retrieval"] = retrieve_meta
        inner["evidence_bundle"] = build_evidence_bundle(evidence, retrieve_meta)
        inner["evidence_ready"] = True
        inner["needs_evidence"] = False
        inner["phase"] = "EVIDENCE_READY"
        if retrieve_meta.get("fallback") and retrieve_meta.get("error"):
            inner.setdefault("fallbacks", []).append("vector_retrieve_failed_local_keyword_used")
        if not evidence:
            inner.setdefault("fallbacks", []).append("no_matching_evidence")
        log_a2a(conn, task_id, "Knowledge RAG Agent", "Note Skill Agent", "evidence_bundle_ready", {"count": len(evidence), "scope": payload.chat_scope, "evidence_bundle": inner["evidence_bundle"]})
        return inner

    def note_handler(inner: AgentState) -> AgentState:
        if not paper:
            inner["phase"] = "ERROR"
            inner["error"] = "Generating a note requires a current paper."
            return inner
        trace("note_skill_agent_node", "Note Skill Agent", "generate_note", "phase=EVIDENCE_READY")
        _, quality, phases, evidence, note_fallbacks, note_generation = generate_note(
            conn,
            gateway,
            task_id,
            paper,
            payload.message,
            inner.get("rag_evidence", []),
            inner.get("retrieve_meta") or inner.get("retrieval") or {},
        )
        inner["note_quality_check"] = quality
        inner["note_generation"] = note_generation
        inner["note_id"] = note_generation.get("note_id")
        inner["note_vector_status"] = note_generation.get("note_vector_status", "")
        inner["obsidian_note_path"] = note_generation.get("markdown_path", "")
        inner["obsidian_pdf_path"] = note_generation.get("pdf_attachment_path", "")
        inner["skill_phases"] = phases
        inner["rag_evidence"] = evidence
        inner.setdefault("fallbacks", []).extend(note_fallbacks)
        inner["note_ready"] = True
        inner["phase"] = "NOTE_READY"
        if has_partial_note_fallback(inner.get("fallbacks", [])):
            inner["answer"] = f"已为《{paper['title']}》生成降级版 Obsidian 阅读笔记，部分章节可能需要人工补充。"
        else:
            inner["answer"] = f"已为《{paper['title']}》生成 Obsidian Markdown 阅读笔记。"
        inner["message_type"] = "note_generated"
        inner["artifacts"] = {"markdown_path": paper.get("obsidian_note_path", ""), "pdf_path": paper.get("file_path", "")}
        return inner

    def answer_handler(inner: AgentState) -> AgentState:
        trace("note_skill_agent_node", "Note Skill Agent", "answer_chat", "phase=EVIDENCE_READY")
        fallbacks = inner.setdefault("fallbacks", [])
        answer = synthesize_answer_from_bundle_with_optional_llm(
            gateway,
            task_id,
            payload.message,
            inner.get("rag_evidence", []),
            inner.get("evidence_bundle") or build_evidence_bundle(inner.get("rag_evidence", []), inner.get("retrieval") or {}),
            inner.get("retrieval") or {},
            payload.chat_scope,
            fallbacks,
        )
        inner["answer"] = answer
        inner["message_type"] = "assistant_answer"
        inner["phase"] = "ANSWER_READY"
        return inner

    final_state = run_graph(
        state,
        lambda inner: knowledge_rag_agent_node(inner, import_handler, retrieve_handler),
        lambda inner: note_skill_agent_node(inner, note_handler, answer_handler),
    )
    trace("finish_node", "Harness", "finish", f"phase={final_state.get('phase')}; status={final_state.get('status')}")
    return final_state


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

