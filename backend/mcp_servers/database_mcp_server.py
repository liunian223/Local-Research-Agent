from __future__ import annotations

import json
from typing import Any

from database import new_id, now_iso, rows_to_dicts
from semantic_chunker import chunk_to_db_row, chunk_to_document_row


def list_folders(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM folders ORDER BY is_system DESC, created_at ASC").fetchall()
    return rows_to_dicts(rows)


def list_papers_by_folder(conn: Any, folder_id: str) -> list[dict[str, Any]]:
    if folder_id == "folder_all":
        rows = conn.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM papers WHERE folder_id = ? ORDER BY created_at DESC", (folder_id,)).fetchall()
    return rows_to_dicts(rows)


def search_papers_by_title_author(conn: Any, keyword: str) -> list[dict[str, Any]]:
    like = f"%{keyword.strip()}%"
    rows = conn.execute(
        "SELECT * FROM papers WHERE title LIKE ? OR authors LIKE ? ORDER BY created_at DESC",
        (like, like),
    ).fetchall()
    return rows_to_dicts(rows)


def insert_paper(conn: Any, paper: dict[str, Any]) -> dict[str, Any]:
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
    return paper


def insert_chunks(conn: Any, document: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    paper_id = document["paper_id"]
    delete_paper_artifacts(conn, [paper_id], include_paper=False, include_notes=False, clear_task_refs=False)
    now = now_iso()
    for page in document.get("pages", []):
        conn.execute(
            """
            INSERT INTO document_pages
            (id, paper_id, page_number, width, height, header_text, footer_text, main_text, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                page["page_id"],
                paper_id,
                page.get("page_number"),
                page.get("width"),
                page.get("height"),
                page.get("header_text", ""),
                page.get("footer_text", ""),
                page.get("main_text", ""),
                json.dumps(page, ensure_ascii=False),
                now,
            ),
        )
    for section in document.get("sections", []):
        conn.execute(
            """
            INSERT INTO document_sections
            (id, paper_id, title, normalized_name, level, parent_section_id, section_path, page_start, page_end, summary,
             metadata_json, is_abstract, section_role, detection_confidence, boundary_source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                section["section_id"],
                paper_id,
                section.get("title", ""),
                section.get("normalized_name", "unknown"),
                section.get("level", 1),
                section.get("parent_section_id"),
                section.get("section_path", ""),
                section.get("page_start"),
                section.get("page_end"),
                section.get("summary", ""),
                json.dumps(section, ensure_ascii=False),
                1 if section.get("is_abstract") else 0,
                section.get("section_role", ""),
                section.get("detection_confidence", 0.0),
                section.get("boundary_source", ""),
                now,
            ),
        )
    for block in document.get("text_blocks", []):
        conn.execute(
            """
            INSERT INTO document_blocks
            (id, paper_id, page_number, block_type, text, bbox_json, section_id, reading_order, is_header, is_footer, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                block["block_id"],
                paper_id,
                block.get("page_number"),
                block.get("block_type", "text"),
                block.get("text", ""),
                json.dumps(block.get("bbox") or [], ensure_ascii=False),
                block.get("section_id", ""),
                block.get("reading_order", 0),
                1 if block.get("is_header") else 0,
                1 if block.get("is_footer") else 0,
                json.dumps(block, ensure_ascii=False),
                now,
            ),
        )
    for table in document.get("tables", []):
        conn.execute(
            """
            INSERT INTO document_tables
            (id, paper_id, page_number, section_id, section_path, caption, bbox_json, columns_json, row_count, structured_text, summary, nearby_text, extraction_status, warnings_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                table["table_id"],
                paper_id,
                table.get("page_number"),
                table.get("section_id", ""),
                table.get("section_path", ""),
                table.get("caption", ""),
                json.dumps(table.get("bbox") or [], ensure_ascii=False),
                json.dumps(table.get("columns") or [], ensure_ascii=False),
                table.get("row_count", 0),
                table.get("structured_text", ""),
                table.get("summary", ""),
                table.get("nearby_text", ""),
                table.get("extraction_status", "partial"),
                json.dumps(table.get("warnings") or [], ensure_ascii=False),
                json.dumps(table, ensure_ascii=False),
                now,
            ),
        )
    for figure in document.get("figures", []):
        conn.execute(
            """
            INSERT INTO document_figures
            (id, paper_id, page_number, section_id, section_path, caption, bbox_json, image_path, nearby_text, visual_summary, summary_source, extraction_status, warnings_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                figure["figure_id"],
                paper_id,
                figure.get("page_number"),
                figure.get("section_id", ""),
                figure.get("section_path", ""),
                figure.get("caption", ""),
                json.dumps(figure.get("bbox") or [], ensure_ascii=False),
                figure.get("image_path", ""),
                figure.get("nearby_text", ""),
                figure.get("visual_summary", ""),
                figure.get("summary_source", "caption_nearby_text"),
                figure.get("extraction_status", "partial"),
                json.dumps(figure.get("warnings") or [], ensure_ascii=False),
                json.dumps(figure, ensure_ascii=False),
                now,
            ),
        )
    for chunk in chunks:
        conn.execute(
            """
            INSERT INTO document_chunks
            (id, paper_id, source_type, title, authors, section_id, section_title, section_path, page_start, page_end,
              block_ids_json, table_ids_json, figure_ids_json, prev_chunk_id, next_chunk_id, context_prefix, content,
              summary, parser_version, indexed_at, metadata_json, is_abstract, retrieval_weight, chunk_role, parent_section_role, created_at)
            VALUES
            (:id, :paper_id, :source_type, :title, :authors, :section_id, :section_title, :section_path, :page_start, :page_end,
              :block_ids_json, :table_ids_json, :figure_ids_json, :prev_chunk_id, :next_chunk_id, :context_prefix, :content,
              :summary, :parser_version, :indexed_at, :metadata_json, :is_abstract, :retrieval_weight, :chunk_role, :parent_section_role, :created_at)
            """,
            chunk_to_document_row(chunk),
        )
        conn.execute(
            """
            INSERT INTO paper_chunks
            (id, paper_id, section_name, chunk_index, text, vector_id, source_type, section_id, section_path, page_start, page_end,
             context_prefix, metadata_json, is_abstract, retrieval_weight, chunk_role, section_role, created_at)
            VALUES
            (:id, :paper_id, :section_name, :chunk_index, :text, :vector_id, :source_type, :section_id, :section_path, :page_start, :page_end,
             :context_prefix, :metadata_json, :is_abstract, :retrieval_weight, :chunk_role, :section_role, :created_at)
            """,
            chunk_to_db_row(chunk),
        )
        for linked_type, key in [("table", "table_ids"), ("figure", "figure_ids"), ("block", "block_ids")]:
            for linked_id in chunk.get(key, []) or []:
                conn.execute(
                    "INSERT INTO chunk_links (id, paper_id, chunk_id, linked_type, linked_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id("link"), paper_id, chunk["id"], linked_type, linked_id, now),
                )
    return {
        "paper_id": paper_id,
        "pages": len(document.get("pages", [])),
        "sections": len(document.get("sections", [])),
        "blocks": len(document.get("text_blocks", [])),
        "tables": len(document.get("tables", [])),
        "figures": len(document.get("figures", [])),
        "chunks": len(chunks),
    }


def insert_image_assets(conn: Any, assets: list[dict[str, Any]]) -> dict[str, Any]:
    now = now_iso()
    inserted = 0
    for asset in assets:
        conn.execute(
            """
            INSERT OR REPLACE INTO image_assets
            (id, paper_id, page_no, image_index, image_path, source_type, width, height, caption, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset.get("image_id") or asset.get("id") or new_id("img"),
                asset["paper_id"],
                asset.get("page_no"),
                asset.get("image_index"),
                asset["image_path"],
                asset["source_type"],
                asset.get("width"),
                asset.get("height"),
                asset.get("caption", ""),
                asset.get("created_at") or now,
            ),
        )
        inserted += 1
    return {"inserted": inserted}


def delete_paper_artifacts(
    conn: Any,
    paper_ids: list[str],
    *,
    include_paper: bool = True,
    include_notes: bool = True,
    clear_task_refs: bool = True,
) -> dict[str, Any]:
    if not paper_ids:
        return {"deleted_papers": 0, "paper_ids": []}
    placeholders = ",".join("?" for _ in paper_ids)
    tables = [
        "chunk_links",
        "image_assets",
        "document_chunks",
        "document_figures",
        "document_tables",
        "document_blocks",
        "document_sections",
        "document_pages",
        "paper_chunks",
    ]
    if include_notes:
        tables = ["note_chunks", "reading_notes", *tables]
    counts: dict[str, int] = {}
    for table in tables:
        before = conn.total_changes
        conn.execute(f"DELETE FROM {table} WHERE paper_id IN ({placeholders})", paper_ids)
        counts[table] = conn.total_changes - before
    if include_paper:
        before = conn.total_changes
        conn.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", paper_ids)
        counts["papers"] = conn.total_changes - before
    if clear_task_refs:
        before = conn.total_changes
        conn.execute(f"UPDATE agent_tasks SET current_paper_id = NULL WHERE current_paper_id IN ({placeholders})", paper_ids)
        counts["agent_tasks_cleared"] = conn.total_changes - before
    return {"deleted_papers": len(paper_ids), "paper_ids": paper_ids, "counts": counts}


def insert_note(conn: Any, note: dict[str, Any]) -> dict[str, Any]:
    conn.execute(
        "INSERT INTO reading_notes (id, paper_id, content_markdown, obsidian_path, quality_check_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            note["id"],
            note["paper_id"],
            note.get("content_markdown", ""),
            note.get("obsidian_path", ""),
            note.get("quality_check_json", "{}"),
            note.get("created_at"),
            note.get("updated_at"),
        ),
    )
    return note


def insert_note_chunks(conn: Any, chunks: list[dict[str, Any]]) -> int:
    for chunk in chunks:
        conn.execute(
            "INSERT INTO note_chunks (id, note_id, paper_id, section_name, chunk_index, text, vector_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk["id"],
                chunk["note_id"],
                chunk["paper_id"],
                chunk.get("section_name", "Note"),
                chunk.get("chunk_index", 0),
                chunk.get("text", ""),
                chunk.get("vector_id") or chunk["id"],
                chunk.get("created_at"),
            ),
        )
    return len(chunks)


def update_paper_status(conn: Any, paper_id: str, note_status: str, obsidian_note_path: str) -> str:
    from database import now_iso

    conn.execute(
        "UPDATE papers SET note_status = ?, obsidian_note_path = ?, updated_at = ? WHERE id = ?",
        (note_status, obsidian_note_path, now_iso(), paper_id),
    )
    return note_status
