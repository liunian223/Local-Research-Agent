from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config
from deepseek_client import build_note_generation_prompt_text, build_rag_answer_prompt_text
from database import log_a2a, log_mcp, new_id, now_iso, row_to_dict, rows_to_dicts
from graph.state import AgentState
from harness.graph_runner import run_chat_agent_graph, run_upload_agent_graph
from harness.runtime import RuntimeTaskError
from layout_parser import parse_pdf_layout, save_layout_artifacts
from llm.model_gateway import get_model_gateway
from mcp_servers.database_mcp_server import insert_chunks, insert_image_assets, insert_note, insert_note_chunks, insert_paper, update_paper_status
from mcp_servers.file_mcp_server import copy_pdf_to_obsidian, read_pdf_text, save_uploaded_pdf, write_markdown_note
from note_skill import check_required_note_sections, quality_json, run_deep_paper_note_skill, safe_obsidian_attachment_path, safe_obsidian_path
from pdf_tools import extract_metadata, safe_filename, sha256_bytes
from rag import note_to_chunks
from semantic_chunker import build_semantic_chunks
from structured_retriever import build_evidence_bundle, collect_structured_scope_chunks, retrieve_structured_evidence
from tool_gateway import ToolGateway
from vector_store import VECTOR_STORE
from vision.image_asset_selector import question_requires_vision, select_image_assets
from vision.pdf_image_extractor import extract_pdf_images


def has_partial_note_fallback(fallbacks: list[Any]) -> bool:
    partial_types = {
        "partial_note_fallback",
        "long_paper_staged_generation",
        "llm_note_generation_failed_local_note_used",
        "llm_note_generation_incomplete_local_note_used",
        "model_note_generation_failed_local_note_used",
        "model_note_missing_required_sections_local_note_used",
    }
    return any(
        (isinstance(item, dict) and item.get("type") in partial_types)
        or (isinstance(item, str) and item in partial_types)
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
            or (isinstance(item, str) and item in local_note_fallbacks)
        )
    ]


def explain_note_partial_reasons(reasons: list[str]) -> list[str]:
    labels = {
        "llm_note_generation_failed_local_note_used": "model_note_generation failed, so the local note template was used",
        "llm_note_generation_incomplete_local_note_used": "model_note_generation missed required sections, so the local note template was used",
        "llm_note_missing_required_sections": "model_note_generation missed required note sections",
        "local_template_used": "local note template fallback was used",
        "insufficient_key_section_evidence": "key section evidence is incomplete",
        "llm_note_generation_not_successful": "llm_note_generation did not finish successfully",
    }
    return [labels.get(reason, reason) for reason in reasons]


def format_note_downgrade_for_answer(note_generation: dict[str, Any]) -> str:
    reasons = note_generation.get("downgrade_reasons") or explain_note_partial_reasons(note_generation.get("partial_reasons") or [])
    if not reasons:
        return "note generation finished with partial status"
    return "; ".join(str(reason) for reason in reasons[:3])


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
    if question_requires_vision(message):
        return "vision_chat"
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


NOTE_RETRIEVAL_PLAN: list[dict[str, Any]] = [
    {"name": "abstract", "query": "abstract summary contribution problem", "keywords": ["abstract", "摘要"], "limit": 2},
    {"name": "introduction", "query": "introduction background motivation problem related work", "keywords": ["introduction", "background", "motivation", "related work", "引言", "背景"], "limit": 2},
    {"name": "method", "query": "method methodology approach model framework algorithm", "keywords": ["method", "methodology", "approach", "model", "framework", "algorithm", "方法", "模型", "算法"], "limit": 3},
    {"name": "experiment", "query": "experiment evaluation setup dataset baseline metrics", "keywords": ["experiment", "evaluation", "dataset", "baseline", "metric", "实验", "评测"], "limit": 3},
    {"name": "result", "query": "results findings performance analysis ablation table figure", "keywords": ["result", "finding", "performance", "ablation", "结果", "分析"], "limit": 3},
    {"name": "discussion", "query": "discussion implication analysis interpretation", "keywords": ["discussion", "implication", "analysis", "讨论"], "limit": 2},
    {"name": "conclusion", "query": "conclusion limitation future work", "keywords": ["conclusion", "limitation", "future work", "结论", "局限"], "limit": 2},
]

NOTE_KEY_EVIDENCE_SECTIONS = ["abstract", "introduction", "method", "experiment", "result", "conclusion"]

NOTE_RETRIEVAL_PLAN = [
    {"name": "abstract", "query": "abstract summary contribution problem", "keywords": ["abstract"], "limit": 2},
    {"name": "background_introduction", "query": "background introduction motivation problem related work", "keywords": ["introduction", "background", "motivation", "related work"], "limit": 3},
    {"name": "method", "query": "method methodology approach model framework algorithm", "keywords": ["method", "methodology", "approach", "model", "framework", "algorithm"], "limit": 3},
    {"name": "experiment", "query": "experiment evaluation setup dataset baseline metrics", "keywords": ["experiment", "evaluation", "dataset", "baseline", "metric"], "limit": 3},
    {"name": "result", "query": "results findings performance analysis ablation table figure", "keywords": ["result", "results", "finding", "performance", "ablation"], "limit": 3},
    {"name": "discussion_conclusion", "query": "discussion conclusion implication analysis interpretation future work", "keywords": ["discussion", "conclusion", "implication", "analysis", "future work"], "limit": 3},
    {"name": "limitation", "query": "limitation limitations threats validity weakness future work", "keywords": ["limitation", "limitations", "threats", "weakness", "future work"], "limit": 2},
]


def retrieve_note_plan_evidence(
    gateway: ToolGateway,
    conn: Any,
    paper: dict[str, Any],
    query: str,
    initial_evidence: list[dict[str, Any]] | None = None,
    initial_meta: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paper_id = paper["id"]
    rows = collect_structured_scope_chunks(conn, "paper_only", paper_id)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    plan_counts: dict[str, int] = {}
    plan_backends: dict[str, str] = {}
    original_count = len(initial_evidence or [])

    def add_items(items: list[dict[str, Any]], category: str, source: str, limit: int | None = None) -> int:
        added = 0
        for item in items[: limit or len(items)]:
            text = (item.get("text") or "")[: config.MAX_EVIDENCE_CHARS]
            key = str(item.get("chunk_id") or item.get("id") or f"{item.get('source_type')}:{item.get('section_path')}:{text[:120]}")
            if not text or key in seen:
                continue
            seen.add(key)
            merged.append({**item, "rank": len(merged) + 1, "text": text, "note_plan_category": category, "note_plan_source": source})
            added += 1
        return added

    forced_abstract: list[dict[str, Any]] = []
    forced_abstract.extend(_select_note_rows_for_category(rows, NOTE_RETRIEVAL_PLAN[0], force_abstract=True))
    forced_abstract.extend(item for item in (initial_evidence or []) if _is_note_abstract_item(item))
    abstract_added = add_items(forced_abstract, "abstract", "forced_abstract", 2)
    if abstract_added:
        plan_counts["abstract"] = abstract_added
    if abstract_added < 2:
        abstract_plan = NOTE_RETRIEVAL_PLAN[0]
        abstract_query = " ".join(part for part in [query or paper.get("title", ""), abstract_plan["query"]] if part).strip()
        try:
            abstract_evidence, abstract_meta = retrieve_evidence(gateway, conn, "paper_only", paper_id, abstract_query)
        except Exception as exc:
            abstract_evidence, abstract_meta = [], {"error": str(exc)[:300], "backend": "unknown"}
        added = add_items([item for item in abstract_evidence if _is_note_abstract_item(item)], "abstract", "forced_abstract", 2 - abstract_added)
        plan_counts["abstract"] = plan_counts.get("abstract", 0) + added
        plan_backends["abstract"] = abstract_meta.get("backend", "unknown")

    add_items([item for item in (initial_evidence or []) if not _is_note_abstract_item(item)], "initial", "upstream")
    for plan in NOTE_RETRIEVAL_PLAN:
        if plan["name"] == "abstract":
            continue
        plan_query = " ".join(part for part in [query or paper.get("title", ""), plan["query"]] if part).strip()
        try:
            plan_evidence, plan_meta = retrieve_evidence(gateway, conn, "paper_only", paper_id, plan_query)
        except Exception as exc:
            plan_evidence, plan_meta = [], {"error": str(exc)[:300], "backend": "unknown"}
        added = add_items(plan_evidence, plan["name"], "retriever", plan.get("limit"))
        added += add_items(_select_note_rows_for_category(rows, plan), plan["name"], "structured_chunks", plan.get("limit"))
        plan_counts[plan["name"]] = plan_counts.get(plan["name"], 0) + added
        plan_backends[plan["name"]] = plan_meta.get("backend", "unknown")

    evidence = merged or [
        {**row, "rank": idx + 1, "score": 0, "text": (row.get("text") or "")[: config.MAX_EVIDENCE_CHARS], "note_plan_category": "fallback", "note_plan_source": "structured_chunks"}
        for idx, row in enumerate(rows[:5])
    ]
    for rank, item in enumerate(evidence, start=1):
        item["rank"] = rank
    coverage = assess_note_evidence_coverage(evidence)
    meta = {
        **(initial_meta or {}),
        "retrieval_mode": "note_chapterized_plan",
        "retrieval_intent": "generate_note",
        "note_retrieval_plan": [plan["name"] for plan in NOTE_RETRIEVAL_PLAN],
        "planned_category_counts": plan_counts,
        "planned_backends": plan_backends,
        "initial_evidence_count": original_count,
        "merged_evidence_count": len(evidence),
        "force_abstract_included": bool(plan_counts.get("abstract")),
        "abstract_control": {"mode": "force_include_no_downweight", "forced_top_k": 2},
        "candidate_count": len(rows),
        "evidence_coverage": coverage,
    }
    return evidence, meta


def _is_note_abstract_item(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") or {}
    haystack = " ".join(
        str(value or "")
        for value in [
            item.get("section_name"),
            item.get("section_path"),
            item.get("section_role"),
            item.get("chunk_role"),
            metadata.get("section_role"),
            metadata.get("chunk_role"),
            item.get("text", "")[:200],
        ]
    ).lower()
    return bool(item.get("is_abstract") or metadata.get("is_abstract")) or "abstract" in haystack or "鎽樿" in haystack


def _select_note_rows_for_category(rows: list[dict[str, Any]], plan: dict[str, Any], force_abstract: bool = False) -> list[dict[str, Any]]:
    keywords = [str(keyword).lower() for keyword in plan.get("keywords", [])]
    selected: list[dict[str, Any]] = []
    for row in rows:
        source_type = row.get("source_type") or "text"
        if source_type == "section_summary" and not force_abstract:
            continue
        haystack = " ".join(
            str(row.get(key) or "")
            for key in ["section_name", "section_path", "section_role", "chunk_role", "context_prefix", "text"]
        ).lower()
        is_abstract = bool(row.get("is_abstract")) or "abstract" in haystack or "摘要" in haystack
        is_abstract = _is_note_abstract_item(row) or is_abstract
        if force_abstract:
            matched = is_abstract
        else:
            matched = any(keyword and keyword in haystack for keyword in keywords)
        if matched:
            selected.append({**row, "score": row.get("score", 0), "text": (row.get("text") or "")[: config.MAX_EVIDENCE_CHARS]})
    selected.sort(key=lambda item: (0 if item.get("source_type") != "section_summary" else 1, item.get("page_start") or 9999, item.get("chunk_index") or 9999))
    return selected


def assess_note_evidence_coverage(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {section: 0 for section in NOTE_KEY_EVIDENCE_SECTIONS}
    body_counts = {section: 0 for section in NOTE_KEY_EVIDENCE_SECTIONS}
    for item in evidence:
        section = _classify_note_evidence_section(item)
        if section not in counts:
            continue
        counts[section] += 1
        if item.get("source_type") != "section_summary" and (item.get("text") or "").strip():
            body_counts[section] += 1
    missing = [section for section in NOTE_KEY_EVIDENCE_SECTIONS if counts[section] == 0]
    missing_body = [section for section in NOTE_KEY_EVIDENCE_SECTIONS if body_counts[section] == 0]
    missing_many = len(missing) >= 2 or len(missing_body) >= 3
    return {
        "ok": not missing_many,
        "section_counts": counts,
        "body_section_counts": body_counts,
        "missing_key_evidence": missing,
        "missing_body_evidence": missing_body,
        "missing_many_key_sections": missing_many,
    }


def _classify_note_evidence_section(item: dict[str, Any]) -> str:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ["note_plan_category", "section_role", "chunk_role", "section_name", "section_path", "context_prefix", "text"]
    ).lower()
    if item.get("is_abstract") or "abstract" in haystack or "摘要" in haystack:
        return "abstract"
    mapping = {
        "introduction": ["introduction", "background", "motivation", "related work", "引言", "背景"],
        "method": ["method", "methodology", "approach", "model", "framework", "algorithm", "方法", "模型", "算法"],
        "experiment": ["experiment", "evaluation", "dataset", "baseline", "metric", "实验", "评测"],
        "result": ["result", "finding", "performance", "ablation", "结果"],
        "conclusion": ["conclusion", "discussion", "limitation", "future work", "结论", "讨论", "局限"],
    }
    for section, tokens in mapping.items():
        if any(token in haystack for token in tokens):
            return section
    return "unknown"


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

    evidence_pages = {
        int(item.get("page_start"))
        for item in evidence
        if isinstance(item.get("page_start"), int) and int(item.get("page_start")) > 0
    }
    if evidence_pages:
        placeholders = ",".join("?" for _ in evidence_pages)
        rows = conn.execute(
            f"""
            SELECT * FROM image_assets
            WHERE paper_id = ? AND page_no IN ({placeholders})
            ORDER BY page_no ASC, source_type ASC, image_index ASC
            LIMIT ?
            """,
            (paper_id, *sorted(evidence_pages), limit * 2),
        ).fetchall()
        for row in rows_to_dicts(rows):
            add_item(row.get("image_path") or "", row.get("id") or "image", row.get("caption") or "", row.get("page_no"), row.get("source_type") or "image_asset")
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        rows = conn.execute(
            """
            SELECT * FROM image_assets
            WHERE paper_id = ?
            ORDER BY page_no ASC, source_type ASC, image_index ASC
            LIMIT ?
            """,
            (paper_id, limit * 2),
        ).fetchall()
        for row in rows_to_dicts(rows):
            add_item(row.get("image_path") or "", row.get("id") or "image", row.get("caption") or "", row.get("page_no"), row.get("source_type") or "image_asset")
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
        return row_to_dict(existing) or {}, ["duplicate_pdf_returned_existing_paper"]

    paper_id = new_id("paper")
    filename = f"{paper_id}_{safe_filename(original_name)}.pdf"
    target = (config.PAPER_DIR / filename).resolve()
    if not str(target).startswith(str(config.PAPER_DIR.resolve())):
        raise RuntimeTaskError(400, "invalid_path", "Upload path escapes paper directory.")
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
    image_extraction = {"status": "skipped", "extracted_count": 0, "skipped_small": 0, "errors": []}
    try:
        extraction_result = gateway.invoke(
            "Knowledge RAG Agent",
            "vision",
            "extract_pdf_images",
            extract_pdf_images,
            target,
            paper_id,
            input_summary=f"paper_id={paper_id}",
            output_summarizer=lambda value: f"status={value.get('status')}; extracted={len(value.get('assets', []))}; skipped_small={value.get('skipped_small', 0)}",
        )
        assets = extraction_result.get("assets", [])
        if assets:
            gateway.invoke(
                "Knowledge RAG Agent",
                "database",
                "insert_image_assets",
                insert_image_assets,
                conn,
                assets,
                input_summary=f"paper_id={paper_id}; image_assets={len(assets)}",
                output_summarizer=lambda value: f"inserted={value.get('inserted', 0)}",
            )
        image_extraction = {
            "status": extraction_result.get("status", "unknown"),
            "extracted_count": len(assets),
            "skipped_small": extraction_result.get("skipped_small", 0),
            "errors": extraction_result.get("errors", []),
        }
        if image_extraction["status"] in {"failed", "partial"}:
            fallbacks.append({"type": "pdf_image_extraction_partial", **image_extraction})
    except Exception as exc:
        image_extraction = {"status": "failed", "extracted_count": 0, "skipped_small": 0, "errors": [str(exc)[:300]]}
        fallbacks.append({"type": "pdf_image_extraction_failed", **image_extraction})
    paper["pdf_image_extraction"] = image_extraction
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
    evidence, retrieve_meta = retrieve_note_plan_evidence(gateway, conn, paper, query, evidence, retrieve_meta)
    evidence_bundle = build_evidence_bundle(evidence or [], retrieve_meta or {})
    rows = collect_structured_scope_chunks(conn, "paper_only", paper["id"])
    if not evidence and rows:
        evidence = [{**row, "rank": idx + 1, "score": 0, "text": row.get("text", "")[: config.MAX_EVIDENCE_CHARS]} for idx, row in enumerate(rows[:5])]
        evidence_bundle = build_evidence_bundle(evidence, retrieve_meta or {})
    evidence_coverage = assess_note_evidence_coverage(evidence or [])
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
    local_template_used = True
    llm_note_generation_status = "not_called"
    partial_reasons: list[str] = []
    model_gateway = get_model_gateway()
    system, prompt = build_note_generation_prompt_text(paper, evidence, full_text)
    prompt = f"{prompt}\n\nStructured evidence bundle:\n{format_grouped_evidence_for_prompt(evidence_bundle)}\n\nRules: force include and use the top abstract_chunks as first-class overview evidence for generate_note. Do not downweight abstract evidence in this task, but do not use abstract text as a substitute for missing body method/experiment/result evidence. If body evidence is insufficient, say so."
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
        llm_note_generation_status = "ok"
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
            local_template_used = False
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
            fallbacks.append("llm_note_generation_incomplete_local_note_used")
            llm_note_generation_status = "fallback"
            partial_reasons.append("llm_note_missing_required_sections")
            quality = {**quality, "llm_generated": False, "llm_quality": llm_quality}
            phases.append({"name": "llm_note_generation", "status": "fallback", "summary": "Model note missed required headings; kept local structured note."})
    else:
        fallbacks.append("llm_note_generation_failed_local_note_used")
        llm_note_generation_status = "fallback"
        partial_reasons.append("llm_note_generation_failed_local_note_used")
        log_mcp(conn, task_id, "llm", "model_note_generation", f"{llm_result.model}; images={len(image_paths)}", "Model note generation failed.", status="error", error=llm_result.error)
        phases.append({"name": "llm_note_generation", "status": "fallback", "summary": "Model call failed; used local note template."})
    if local_template_used:
        partial_reasons.append("local_template_used")
    if not evidence_coverage["ok"]:
        partial_reasons.append("insufficient_key_section_evidence")
        phases.append({"name": "evidence_quality_check", "status": "partial", "summary": f"Missing key evidence: {', '.join(evidence_coverage['missing_key_evidence']) or 'none'}; missing body evidence: {', '.join(evidence_coverage['missing_body_evidence']) or 'none'}."})
    else:
        phases.append({"name": "evidence_quality_check", "status": "success", "summary": "Required key section evidence is covered."})
    if any(phase.get("name") == "llm_note_generation" and phase.get("status") in {"fallback", "error"} for phase in phases):
        partial_reasons.append("llm_note_generation_not_successful")
    partial_reasons = sorted(set(partial_reasons))
    downgrade_reasons = explain_note_partial_reasons(partial_reasons)
    if not evidence_coverage["ok"]:
        quality["ok"] = False
    quality = {
        **quality,
        "evidence_coverage": evidence_coverage,
        "evidence_coverage_ok": evidence_coverage["ok"],
        "local_template_used": local_template_used,
        "llm_note_generation_status": llm_note_generation_status,
        "partial_reasons": partial_reasons,
        "downgrade_reasons": downgrade_reasons,
    }
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
    note_status = "partial" if partial_reasons or local_template_used or llm_note_generation_status in {"fallback", "error"} else "done"
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
        "status": note_status,
        "mode": quality.get("note_generation_mode") or ("long_paper" if quality.get("long_paper") else "normal"),
        "template_version": quality.get("template_version") or "obsidian_note_v2",
        "quality_check": quality,
        "local_template_used": local_template_used,
        "llm_note_generation_status": llm_note_generation_status,
        "partial_reasons": partial_reasons,
        "downgrade_reasons": downgrade_reasons,
        "repair_rounds": quality.get("repair_rounds", 0),
        "repair_log": quality.get("repair_log", []),
        "note_id": note_id,
        "note_chunks": len(note_chunks),
        "note_vector_status": note_index_result.get("status", "unknown"),
        "vector_backend": note_index_result.get("backend", ""),
        "markdown_path": str(note_path),
        "pdf_attachment_path": str(attachment_path),
        "evidence_group_counts": quality.get("evidence_group_counts", {}),
        "evidence_coverage": evidence_coverage,
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


def handle_vision_chat(
    conn: Any,
    gateway: ToolGateway,
    task_id: str,
    paper: dict[str, Any] | None,
    question: str,
    evidence: list[dict[str, Any]],
    retrieval: dict[str, Any],
    chat_scope: str,
    fallbacks: list[Any],
) -> tuple[str, dict[str, Any]]:
    if not paper:
        fallbacks.append("vision_chat_requires_current_paper")
        answer = synthesize_answer_from_bundle_with_optional_llm(
            gateway,
            task_id,
            question,
            evidence,
            build_evidence_bundle(evidence, retrieval),
            retrieval,
            chat_scope,
            fallbacks,
        )
        return answer, {"status": "fallback", "fallback_reason": "missing_current_paper"}

    selection = select_image_assets(
        conn,
        paper_id=paper["id"],
        question=question,
        evidence=evidence,
        pdf_path=paper.get("file_path", ""),
    )
    rendered_assets = selection.get("rendered_assets", [])
    if rendered_assets:
        try:
            insert_image_assets(conn, rendered_assets)
        except Exception as exc:
            fallbacks.append({"type": "rendered_page_asset_db_insert_failed", "message": str(exc)[:300]})

    selected_paths = selection.get("selected_image_paths", [])
    vision_execution = {
        "status": "skipped",
        "selected_image_assets": selection.get("selected_assets", []),
        "selected_image_paths": selected_paths,
        "rendered_pages": rendered_assets,
        "rendered_image_paths": selection.get("rendered_image_paths", []),
        "target_pages": selection.get("target_pages", []),
        "render_status": selection.get("render_status", ""),
        "render_errors": selection.get("render_errors", []),
        "available_asset_count": selection.get("available_asset_count", 0),
        "codex_vision_status": "not_called",
    }
    if not selected_paths:
        fallbacks.append("vision_chat_no_images_text_rag_used")
        answer = synthesize_answer_from_bundle_with_optional_llm(
            gateway,
            task_id,
            question,
            evidence,
            build_evidence_bundle(evidence, retrieval),
            retrieval,
            chat_scope,
            fallbacks,
        )
        vision_execution.update({"status": "fallback", "fallback_reason": "no_selected_images"})
        return answer, vision_execution

    evidence_lines = []
    for item in evidence[: config.MAX_EVIDENCE_ITEMS]:
        page = item.get("page_start") or item.get("page_no") or ""
        section = item.get("section_path") or item.get("section_name") or "Body"
        evidence_lines.append(f"- page={page} section={section}: {(item.get('text') or '')[:500]}")
    prompt = f"""用户问题:
{question}

当前论文:
- title: {paper.get('title') or ''}
- authors: {paper.get('authors') or ''}
- paper_id: {paper.get('id') or ''}

RAG evidence 摘要:
{chr(10).join(evidence_lines) or 'No textual evidence retrieved.'}

图像路径:
{chr(10).join(selected_paths)}

要求:
1. 用中文回答。
2. 只依据文本 evidence 和这些 PDF 派生图像回答。
3. 不要编造图像中不存在或看不清的信息；看不清时直接说明。
4. 区分图像观察、图注/附近文本、以及推理。
"""
    result = get_model_gateway().generate_text(
        prompt,
        system="You are the Note Skill Agent vision handler. Ground answers in PDF-derived images and local RAG evidence.",
        purpose="vision_chat",
        temperature=0.2,
        max_output_tokens=1600,
        image_paths=selected_paths,
    )
    if result.ok:
        log_mcp(gateway.conn, task_id, "llm", "codex_vision_chat", f"{result.model}; images={len(selected_paths)}", result.usage_summary or "Codex vision answer generated.")
        vision_execution.update({"status": "success", "codex_vision_status": "success", "model": result.model, "usage_summary": result.usage_summary})
        return result.content, vision_execution

    fallbacks.append({"type": "codex_vision_failed", "message": result.error})
    log_mcp(gateway.conn, task_id, "llm", "codex_vision_chat", f"{result.model}; images={len(selected_paths)}", "Codex vision call failed.", status="error", error=result.error)
    answer = synthesize_answer_from_bundle_with_optional_llm(
        gateway,
        task_id,
        question,
        evidence,
        build_evidence_bundle(evidence, retrieval),
        retrieval,
        chat_scope,
        fallbacks,
    )
    vision_execution.update({"status": "fallback", "codex_vision_status": "failed", "fallback_reason": "codex_vision_failed", "error": result.error})
    return answer, vision_execution


def run_upload_graph(conn: Any, task_id: str, task_type: str, file_bytes: bytes, file_name: str, folder_id: str, message: str) -> AgentState:
    def import_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
        paper, fallbacks = ingest_pdf(conn, gateway, task_id, file_bytes, file_name, folder_id)
        inner["paper"] = paper
        inner["current_paper_id"] = paper["id"]
        inner["pdf_image_extraction"] = paper.get("pdf_image_extraction", {})
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

    def retrieve_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
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

    def note_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
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
        note_is_partial = note_generation.get("status") == "partial" or note_generation.get("local_template_used") or has_partial_note_fallback(inner.get("fallbacks", []))
        if note_is_partial:
            inner["answer"] = f"已导入 PDF《{paper['title']}》，并生成降级版 Obsidian 阅读笔记，部分章节可能需要人工补充。"
            downgrade_reason = format_note_downgrade_for_answer(note_generation)
            inner["answer"] = f"Generated a partial Obsidian reading note for {paper['title']}. Downgrade reason: {downgrade_reason}. Some sections may need manual completion."
            inner["task_status"] = "partial"
            inner["message_type"] = "partial_success"
        else:
            inner["answer"] = f"已导入 PDF《{paper['title']}》，并生成 Obsidian Markdown 阅读笔记。"
            inner["task_status"] = "done"
            inner["message_type"] = "note_generated"
        inner["artifacts"] = {
            "markdown_path": paper.get("obsidian_note_path", ""),
            "pdf_path": paper["file_path"],
            "obsidian_pdf_path": paper.get("obsidian_pdf_path", ""),
        }
        return inner

    def answer_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
        inner["phase"] = "ERROR"
        inner["error"] = "Upload graph should not answer chat."
        return inner

    return run_upload_agent_graph(
        conn=conn,
        task_id=task_id,
        task_type=task_type,
        file_bytes=file_bytes,
        file_name=file_name,
        folder_id=folder_id,
        message=message,
        import_handler=import_handler,
        retrieve_handler=retrieve_handler,
        generate_note_handler=note_handler,
        answer_chat_handler=answer_handler,
    )


def run_chat_graph(conn: Any, task_id: str, payload: ChatMessage, paper: dict[str, Any] | None) -> AgentState:
    task_type = task_type_from_message(payload.message)

    def import_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
        inner["phase"] = "ERROR"
        inner["error"] = "Chat graph should not import paper."
        return inner

    def retrieve_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
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

    def note_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
        if not paper:
            inner["phase"] = "ERROR"
            inner["error"] = "Generating a note requires a current paper."
            return inner
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
        note_is_partial = note_generation.get("status") == "partial" or note_generation.get("local_template_used") or has_partial_note_fallback(inner.get("fallbacks", []))
        if note_is_partial:
            inner["answer"] = f"已为《{paper['title']}》生成降级版 Obsidian 阅读笔记，部分章节可能需要人工补充。"
            downgrade_reason = format_note_downgrade_for_answer(note_generation)
            inner["answer"] = f"Generated a partial Obsidian reading note for {paper['title']}. Downgrade reason: {downgrade_reason}. Some sections may need manual completion."
            inner["task_status"] = "partial"
            inner["message_type"] = "partial_success"
        else:
            inner["answer"] = f"已为《{paper['title']}》生成 Obsidian Markdown 阅读笔记。"
            inner["task_status"] = "done"
            inner["message_type"] = "note_generated"
        inner["artifacts"] = {"markdown_path": paper.get("obsidian_note_path", ""), "pdf_path": paper.get("file_path", "")}
        return inner

    def answer_handler(inner: AgentState, gateway: ToolGateway) -> AgentState:
        fallbacks = inner.setdefault("fallbacks", [])
        if task_type == "vision_chat":
            answer, vision_execution = handle_vision_chat(
                conn,
                gateway,
                task_id,
                paper,
                payload.message,
                inner.get("rag_evidence", []),
                inner.get("retrieval") or {},
                payload.chat_scope,
                fallbacks,
            )
            inner["vision_required"] = True
            inner["vision_answer"] = answer
            inner["vision_execution"] = vision_execution
            inner["image_assets"] = vision_execution.get("selected_image_assets", [])
            inner["selected_image_paths"] = vision_execution.get("selected_image_paths", [])
            inner["rendered_image_paths"] = vision_execution.get("rendered_image_paths", [])
        else:
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

    return run_chat_agent_graph(
        conn=conn,
        task_id=task_id,
        task_type=task_type,
        message=payload.message,
        current_paper_id=payload.current_paper_id,
        current_folder_id=payload.current_folder_id,
        chat_scope=payload.chat_scope,
        paper=paper,
        import_handler=import_handler,
        retrieve_handler=retrieve_handler,
        generate_note_handler=note_handler,
        answer_chat_handler=answer_handler,
    )


