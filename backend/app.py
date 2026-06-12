from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from agents.knowledge_rag_agent import knowledge_rag_agent_node
from agents.note_skill_agent import note_skill_agent_node
from deepseek_client import build_note_generation_prompt, build_rag_answer_prompt, get_deepseek_client
from database import connect, init_db, log_a2a, log_mcp, log_trace, new_id, now_iso, row_to_dict, rows_to_dicts
from graph.builder import run_graph
from graph.state import AgentState
from graph_runtime import initial_phase, standard_flow, validate_node_visits
from note_skill import check_required_note_sections, quality_json, run_deep_paper_note_skill, safe_obsidian_attachment_path, safe_obsidian_path
from pdf_tools import extract_metadata, extract_text_with_fallback, safe_filename, sha256_bytes
from rag import note_to_chunks, split_chunks
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
    chat_scope: str = "paper_and_note"


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
def health() -> dict[str, str]:
    return {"status": "ok", "project": config.PROJECT_NAME}


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
def search_papers(keyword: str = "") -> dict[str, Any]:
    like = f"%{keyword.strip()}%"
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM papers WHERE title LIKE ? OR authors LIKE ? ORDER BY created_at DESC",
            (like, like),
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
        deleted_papers = delete_papers(conn, [paper_dict(paper)])
    return {"status": "deleted", "deleted_papers": deleted_papers}


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


def delete_papers(conn: Any, papers: list[dict[str, Any]]) -> int:
    if not papers:
        return 0
    paper_ids = [paper["id"] for paper in papers]
    placeholders = ",".join("?" for _ in paper_ids)
    roots = [config.PAPER_DIR, config.PARSED_DIR, config.OBSIDIAN_VAULT_PATH]
    for paper in papers:
        for path in cleanup_paths_for_paper(paper):
            safe_unlink(path, roots)
    conn.execute(f"DELETE FROM note_chunks WHERE paper_id IN ({placeholders})", paper_ids)
    conn.execute(f"DELETE FROM reading_notes WHERE paper_id IN ({placeholders})", paper_ids)
    conn.execute(f"DELETE FROM paper_chunks WHERE paper_id IN ({placeholders})", paper_ids)
    conn.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", paper_ids)
    conn.execute(f"UPDATE agent_tasks SET current_paper_id = NULL WHERE current_paper_id IN ({placeholders})", paper_ids)
    return len(paper_ids)


def collect_scope_chunks(conn: Any, scope: str, paper_id: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if scope in {"paper_only", "paper_and_note"}:
        if paper_id:
            paper_rows = conn.execute("SELECT *, 'paper' AS source_type FROM paper_chunks WHERE paper_id = ?", (paper_id,)).fetchall()
        else:
            paper_rows = conn.execute("SELECT *, 'paper' AS source_type FROM paper_chunks").fetchall()
        rows.extend(rows_to_dicts(paper_rows))
    if scope in {"note_only", "paper_and_note"}:
        if paper_id:
            note_rows = conn.execute("SELECT *, 'note' AS source_type FROM note_chunks WHERE paper_id = ?", (paper_id,)).fetchall()
        else:
            note_rows = conn.execute("SELECT *, 'note' AS source_type FROM note_chunks").fetchall()
        rows.extend(rows_to_dicts(note_rows))
    if scope == "global_library":
        rows.extend(rows_to_dicts(conn.execute("SELECT *, 'paper' AS source_type FROM paper_chunks").fetchall()))
        rows.extend(rows_to_dicts(conn.execute("SELECT *, 'note' AS source_type FROM note_chunks").fetchall()))
    return rows


def execution_from(conn: Any, task_id: str, evidence: list[dict[str, Any]], skill_phases: list[dict[str, Any]], fallbacks: list[str]) -> dict[str, Any]:
    traces = rows_to_dicts(conn.execute("SELECT * FROM agent_traces WHERE task_id = ? ORDER BY step_index ASC", (task_id,)).fetchall())
    mcp = rows_to_dicts(conn.execute("SELECT * FROM mcp_tool_calls WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall())
    a2a = rows_to_dicts(conn.execute("SELECT * FROM a2a_messages WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall())
    task = row_to_dict(conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()) or {}
    visited = [trace["node_name"] for trace in traces]
    visits_ok, visits_error = validate_node_visits(visited)
    return {
        "graph_state": {
            "task_type": task.get("task_type"),
            "initial_phase": initial_phase(task.get("task_type", "")),
            "standard_flow": standard_flow(task.get("task_type", "")),
            "node_visit_limit_ok": visits_ok,
            "node_visit_limit_error": visits_error,
        },
        "langgraph_nodes": traces,
        "mcp_tool_calls": mcp,
        "a2a_messages": a2a,
        "skill_phases": skill_phases,
        "rag_evidence": evidence,
        "fallbacks": fallbacks,
    }


def history_message_text(task: dict[str, Any]) -> str:
    if task.get("user_input"):
        return task["user_input"]
    if task.get("task_type") in {"import_paper", "import_and_note"}:
        return "上传 PDF"
    return ""


@app.get("/api/chat/history")
def chat_history(limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM agent_tasks
            WHERE status = 'done'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        tasks = list(reversed(rows_to_dicts(rows)))
        messages: list[dict[str, Any]] = []
        for task in tasks:
            user_text = history_message_text(task)
            if user_text:
                messages.append({"role": "user", "text": user_text, "task_id": task["id"]})
            if task.get("answer"):
                messages.append({"role": "assistant", "text": task["answer"], "task_id": task["id"]})

        latest = tasks[-1] if tasks else {}
        paper = None
        if latest.get("current_paper_id"):
            paper = row_to_dict(conn.execute("SELECT * FROM papers WHERE id = ?", (latest["current_paper_id"],)).fetchone())
            if paper:
                note = conn.execute(
                    "SELECT id, obsidian_path, created_at, updated_at FROM reading_notes WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1",
                    (paper["id"],),
                ).fetchone()
                paper["latest_note"] = row_to_dict(note)
    return {
        "messages": messages,
        "current_paper": paper,
        "current_folder_id": latest.get("current_folder_id") or (paper.get("folder_id") if paper else "folder_all"),
        "chat_scope": latest.get("chat_scope") or "paper_and_note",
    }


def has_partial_note_fallback(fallbacks: list[Any]) -> bool:
    return any(
        (isinstance(item, dict) and item.get("type") in {"partial_note_fallback", "long_paper_staged_generation"})
        or item in {"partial_note_fallback", "long_paper_staged_generation"}
        for item in fallbacks
    )


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
    rows = collect_scope_chunks(conn, scope, paper_id)
    return gateway.invoke(
        "Knowledge RAG Agent",
        "rag",
        "retrieve_chunks",
        VECTOR_STORE.retrieve,
        query,
        rows,
        input_summary=f"scope={scope}; paper_id={paper_id or ''}",
        output_summarizer=lambda value: f"{len(value[0])} evidence chunks returned by {value[1].get('backend')}",
    )


def synthesize_answer_with_optional_llm(gateway: ToolGateway, task_id: str, question: str, evidence: list[dict[str, Any]], fallbacks: list[str]) -> str:
    if not evidence:
        fallbacks.append("no_matching_evidence")
        return "没有检索到足够相关的 evidence。你可以先导入 PDF，或切换到全知识库范围后再提问。"

    client = get_deepseek_client()
    if client is None:
        fallbacks.append("deepseek_api_key_missing_local_rag_answer_used")
        bullets = "\n".join(f"- {item['section_name']}: {item['text'][:220]}" for item in evidence[:3])
        return (
            "基于当前范围的本地 evidence，初步回答如下：\n"
            f"{bullets}\n\n"
            "这是离线 RAG 兜底回答；配置 DEEPSEEK_API_KEY 后可接入 DeepSeek 生成更完整的综合回答。"
        )

    result = client.chat(
        build_rag_answer_prompt(question, evidence),
        model=config.DEEPSEEK_MODEL_CHAT,
        temperature=0.2,
        max_tokens=1600,
    )
    if result.ok:
        log_mcp(gateway.conn, task_id, "llm", "deepseek_chat", result.model, result.usage_summary or "DeepSeek answer generated.")
        return result.content

    fallbacks.append("deepseek_chat_failed_local_rag_answer_used")
    log_mcp(gateway.conn, task_id, "llm", "deepseek_chat", result.model, "DeepSeek call failed.", status="error", error=result.error)
    bullets = "\n".join(f"- {item['section_name']}: {item['text'][:220]}" for item in evidence[:3])
    return f"DeepSeek 调用失败，已使用本地 RAG 兜底回答：\n{bullets}"


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
        target.write_bytes,
        file_bytes,
        input_summary=original_name,
        output_summarizer=lambda value: str(target),
    )

    parsed = gateway.invoke(
        "Knowledge RAG Agent",
        "file",
        "read_pdf_text",
        extract_text_with_fallback,
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
    conn.execute(
        """
        INSERT INTO papers
        (id, title, authors, year, language, doi, file_path, file_name, file_sha256, page_count, folder_id,
         parse_status, vector_status, note_status, obsidian_note_path, metadata_source, metadata_confidence,
         metadata_warning, parse_warning, created_at, updated_at)
        VALUES
        (:id, :title, :authors, :year, :language, :doi, :file_path, :file_name, :file_sha256, :page_count, :folder_id,
         :parse_status, :vector_status, :note_status, :obsidian_note_path, :metadata_source, :metadata_confidence,
         :metadata_warning, :parse_warning, :created_at, :updated_at)
        """,
        paper,
    )
    log_mcp(conn, task_id, "database", "insert_paper", paper_id, f"title={paper['title']}; parse_status={parse_status}")

    chunks = split_chunks(parsed["text"], metadata["language"]) if parsed["text"] else []
    for chunk in chunks:
        conn.execute(
            "INSERT INTO paper_chunks (id, paper_id, section_name, chunk_index, text, vector_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chunk["id"], paper_id, chunk["section_name"], chunk["chunk_index"], chunk["text"], chunk["id"], now_iso()),
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


def generate_note(conn: Any, gateway: ToolGateway, task_id: str, paper: dict[str, Any], query: str) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    evidence, _ = retrieve_evidence(gateway, conn, "paper_only", paper["id"], query or paper.get("title", ""))
    rows = collect_scope_chunks(conn, "paper_only", paper["id"])
    if not evidence and rows:
        evidence = [{**row, "rank": idx + 1, "score": 0, "text": row.get("text", "")[: config.MAX_EVIDENCE_CHARS]} for idx, row in enumerate(rows[:5])]
    full_text = "\n\n".join(row.get("text", "") for row in rows)
    skill_result = gateway.invoke(
        "Note Skill Agent",
        "skills",
        "run_deep_paper_note_skill",
        run_deep_paper_note_skill,
        paper,
        full_text,
        evidence,
        "zh",
        input_summary=f"paper_id={paper['id']}; evidence={len(evidence)}; text_chars={len(full_text)}",
        output_summarizer=lambda value: f"status={value['status']}; markdown_chars={len(value['note_markdown'])}; phases={len(value['skill_phases'])}",
    )
    markdown = skill_result["note_markdown"]
    quality = skill_result["quality_check"]
    phases = skill_result["skill_phases"]
    fallbacks: list[Any] = list(skill_result.get("fallbacks", []))
    client = get_deepseek_client()
    if client is None:
        phases.append({"name": "llm_note_generation", "status": "skipped", "summary": "DEEPSEEK_API_KEY is not set; used local note template."})
        fallbacks.append("deepseek_api_key_missing_local_note_used")
    else:
        llm_result = client.chat(
            build_note_generation_prompt(paper, evidence, full_text),
            model=config.DEEPSEEK_MODEL_NOTE,
            temperature=0.2,
            max_tokens=3600,
        )
        if llm_result.ok:
            llm_quality = check_required_note_sections(llm_result.content)
            log_mcp(conn, task_id, "llm", "deepseek_note_generation", llm_result.model, llm_result.usage_summary or "DeepSeek note generated.")
            if llm_quality["ok"]:
                markdown = llm_result.content
                quality = {
                    **quality,
                    **llm_quality,
                    "llm_generated": True,
                    "model": llm_result.model,
                    "usage_summary": llm_result.usage_summary,
                }
                phases.append({"name": "llm_note_generation", "status": "ok", "summary": f"Generated note with {llm_result.model}."})
            else:
                fallbacks.append("deepseek_note_missing_required_sections_local_note_used")
                quality = {**quality, "llm_generated": False, "llm_quality": llm_quality}
                phases.append({"name": "repair_if_needed", "status": "fallback", "summary": "DeepSeek note missed required headings; kept local structured note."})
        else:
            fallbacks.append("deepseek_note_generation_failed_local_note_used")
            log_mcp(conn, task_id, "llm", "deepseek_note_generation", llm_result.model, "DeepSeek note generation failed.", status="error", error=llm_result.error)
            phases.append({"name": "llm_note_generation", "status": "fallback", "summary": "DeepSeek call failed; used local note template."})
    folder = None
    if paper.get("folder_id") and paper["folder_id"] != "folder_all":
        folder = conn.execute("SELECT name FROM folders WHERE id = ?", (paper["folder_id"],)).fetchone()
    note_path = safe_obsidian_path(paper.get("title") or paper["id"], folder["name"] if folder else None)
    gateway.invoke(
        "Note Skill Agent",
        "file",
        "write_markdown_note",
        note_path.write_text,
        markdown,
        encoding="utf-8",
        input_summary=paper.get("title", ""),
        output_summarizer=lambda value: str(note_path),
    )
    attachment_path = safe_obsidian_attachment_path(Path(paper.get("file_path") or paper.get("file_name") or f"{paper['id']}.pdf").name)
    gateway.invoke(
        "Note Skill Agent",
        "file",
        "copy_pdf_to_obsidian",
        lambda source, target: target.write_bytes(source.read_bytes()),
        Path(paper["file_path"]),
        attachment_path,
        input_summary=f"paper_id={paper['id']}",
        output_summarizer=lambda value: str(attachment_path),
    )

    note_id = new_id("note")
    conn.execute(
        "INSERT INTO reading_notes (id, paper_id, content_markdown, obsidian_path, quality_check_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (note_id, paper["id"], markdown, str(note_path), quality_json(quality), now_iso(), now_iso()),
    )
    note_chunks = note_to_chunks(note_id, paper["id"], markdown)
    for chunk in note_chunks:
        conn.execute(
            "INSERT INTO note_chunks (id, note_id, paper_id, section_name, chunk_index, text, vector_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chunk["id"], note_id, paper["id"], chunk["section_name"], chunk["chunk_index"], chunk["text"], chunk["id"], chunk["created_at"]),
        )
    gateway.invoke(
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
    log_mcp(conn, task_id, "database", "insert_note", note_id, f"paper_id={paper['id']}; chunks={len(note_chunks)}")
    conn.execute("UPDATE papers SET note_status = ?, obsidian_note_path = ?, updated_at = ? WHERE id = ?", ("done", str(note_path), now_iso(), paper["id"]))
    paper["note_status"] = "done"
    paper["obsidian_note_path"] = str(note_path)
    paper["obsidian_pdf_path"] = str(attachment_path)
    return markdown, quality, phases, evidence, fallbacks


def run_upload_graph(conn: Any, task_id: str, task_type: str, file_bytes: bytes, file_name: str, folder_id: str, message: str) -> AgentState:
    gateway = ToolGateway(conn, task_id)
    step = {"value": 1}

    def trace(node: str, agent: str, action: str, summary: str) -> None:
        log_trace(conn, task_id, step["value"], node, agent, action, summary)
        step["value"] += 1

    trace("coordinator_node", "Harness", "route_task", f"task_type={task_type}; phase={initial_phase(task_type)}")
    state: AgentState = {
        "task_id": task_id,
        "user_input": message,
        "task_type": task_type,
        "phase": "START",
        "current_folder_id": folder_id,
        "chat_scope": "paper_and_note",
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
        inner["evidence_ready"] = True
        inner["needs_evidence"] = False
        inner["phase"] = "EVIDENCE_READY"
        if not evidence:
            inner.setdefault("fallbacks", []).append("no_relevant_evidence_for_note")
        log_a2a(conn, task_id, "Knowledge RAG Agent", "Note Skill Agent", "evidence_ready", {"count": len(evidence), "scope": "paper_only"})
        return inner

    def note_handler(inner: AgentState) -> AgentState:
        trace("note_skill_agent_node", "Note Skill Agent", "generate_note", "phase=EVIDENCE_READY")
        paper = inner.get("paper") or {}
        _, quality, phases, evidence, note_fallbacks = generate_note(conn, gateway, task_id, paper, message)
        paper["note_status"] = "done"
        inner["paper"] = paper
        inner["note_quality_check"] = quality
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
        "user_input": payload.message,
        "task_type": task_type,
        "phase": "START",
        "current_paper_id": payload.current_paper_id,
        "current_folder_id": payload.current_folder_id,
        "chat_scope": payload.chat_scope,
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
        inner["evidence_ready"] = True
        inner["needs_evidence"] = False
        inner["phase"] = "EVIDENCE_READY"
        if retrieve_meta.get("fallback") and retrieve_meta.get("error"):
            inner.setdefault("fallbacks", []).append("vector_retrieve_failed_local_keyword_used")
        if not evidence:
            inner.setdefault("fallbacks", []).append("no_matching_evidence")
        log_a2a(conn, task_id, "Knowledge RAG Agent", "Note Skill Agent", "evidence_ready", {"count": len(evidence), "scope": payload.chat_scope})
        return inner

    def note_handler(inner: AgentState) -> AgentState:
        if not paper:
            inner["phase"] = "ERROR"
            inner["error"] = "Generating a note requires a current paper."
            return inner
        trace("note_skill_agent_node", "Note Skill Agent", "generate_note", "phase=EVIDENCE_READY")
        _, quality, phases, evidence, note_fallbacks = generate_note(conn, gateway, task_id, paper, payload.message)
        inner["note_quality_check"] = quality
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
        answer = synthesize_answer_with_optional_llm(gateway, task_id, payload.message, inner.get("rag_evidence", []), fallbacks)
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
async def upload_pdf(file: UploadFile = File(...), current_folder_id: str = Form("folder_all"), message: str = Form("")) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_UPLOAD_EXTENSIONS:
        raise api_error(400, "invalid_file_type", "Only PDF files are allowed.")
    validate_pdf_mime(file.content_type)
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise api_error(400, "file_too_large", f"PDF exceeds {config.MAX_UPLOAD_MB} MB.")
    if not content.startswith(b"%PDF"):
        raise api_error(400, "invalid_pdf", "Uploaded file does not look like a PDF.")

    task_id = new_id("task")
    task_type = task_type_from_message(message, has_upload=True)
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_tasks (id, task_type, user_input, status, current_folder_id, chat_scope, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, task_type, message, "running", current_folder_id, "paper_and_note", now_iso(), now_iso()),
        )
        final_state = run_upload_graph(conn, task_id, task_type, content, file.filename or "paper.pdf", current_folder_id, message)
        paper = final_state.get("paper", {})
        answer = final_state.get("answer") or "任务执行中止：检测到异常循环。"
        message_type = final_state.get("message_type") or "assistant_answer"
        evidence = final_state.get("rag_evidence", [])
        skill_phases = final_state.get("skill_phases", [])
        fallbacks = final_state.get("fallbacks", [])
        conn.execute("UPDATE agent_tasks SET status = ?, current_paper_id = ?, answer = ?, updated_at = ? WHERE id = ?", ("done", paper["id"], answer, now_iso(), task_id))
        execution = execution_from(conn, task_id, evidence, skill_phases, fallbacks)
    return {
        "task_id": task_id,
        "answer": answer,
        "message_type": message_type,
        "current_paper": {"paper_id": paper["id"], "title": paper["title"]},
        "artifacts": {
            "markdown_path": paper.get("obsidian_note_path", ""),
            "pdf_path": paper["file_path"],
            "obsidian_pdf_path": paper.get("obsidian_pdf_path", ""),
        },
        "execution": execution,
    }


@app.post("/api/chat/message")
def chat_message(payload: ChatMessage) -> dict[str, Any]:
    if payload.chat_scope not in {"paper_and_note", "paper_only", "note_only", "global_library"}:
        raise api_error(400, "invalid_chat_scope", "Unsupported chat scope.")
    task_id = new_id("task")
    task_type = task_type_from_message(payload.message)
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_tasks (id, task_type, user_input, status, current_paper_id, current_folder_id, chat_scope, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, task_type, payload.message, "running", payload.current_paper_id, payload.current_folder_id, payload.chat_scope, now_iso(), now_iso()),
        )
        paper = None
        if payload.current_paper_id:
            paper = row_to_dict(conn.execute("SELECT * FROM papers WHERE id = ?", (payload.current_paper_id,)).fetchone())
        if task_type == "generate_note" and not paper:
            raise api_error(400, "current_paper_required", "Generating a note requires a current paper.")
        final_state = run_chat_graph(conn, task_id, payload, paper)
        evidence = final_state.get("rag_evidence", [])
        skill_phases = final_state.get("skill_phases", [])
        fallbacks = final_state.get("fallbacks", [])
        answer = final_state.get("answer") or "任务执行中止：检测到异常循环。"
        message_type = final_state.get("message_type") or "assistant_answer"

        conn.execute("UPDATE agent_tasks SET status = ?, answer = ?, updated_at = ? WHERE id = ?", ("done", answer, now_iso(), task_id))
        execution = execution_from(conn, task_id, evidence, skill_phases, fallbacks)
    return {
        "task_id": task_id,
        "answer": answer,
        "message_type": message_type,
        "current_paper": {"paper_id": paper["id"], "title": paper["title"]} if paper else None,
        "artifacts": {
            "markdown_path": paper.get("obsidian_note_path", "") if paper else "",
            "pdf_path": paper.get("file_path", "") if paper else "",
            "obsidian_pdf_path": paper.get("obsidian_pdf_path", "") if paper else "",
        },
        "execution": execution,
    }
