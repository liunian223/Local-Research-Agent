from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import config
from database import connect, row_to_dict, rows_to_dicts
from harness.runtime import RuntimeTaskError
from mcp_servers.database_mcp_server import delete_paper_artifacts
from note_skill import safe_obsidian_attachment_path
from vector_store import VECTOR_STORE


def list_folders_response() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name, is_system, created_at, updated_at FROM folders ORDER BY is_system DESC, created_at ASC").fetchall()
    folders = rows_to_dicts(rows)
    for folder in folders:
        folder["is_system"] = bool(folder["is_system"])
    return {"folders": folders}


def list_papers_response(folder_id: str = "folder_all") -> dict[str, Any]:
    with connect() as conn:
        if folder_id == "folder_all":
            rows = conn.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM papers WHERE folder_id = ? ORDER BY created_at DESC", (folder_id,)).fetchall()
        papers = papers_with_notes(conn, rows)
    return {"papers": papers}


def search_papers_response(keyword: str = "", folder_id: str = "folder_all") -> dict[str, Any]:
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


def get_paper_response(paper_id: str) -> dict[str, Any]:
    with connect() as conn:
        paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not paper:
            raise RuntimeTaskError(404, "paper_not_found", "Paper not found.")
        note = conn.execute("SELECT * FROM reading_notes WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1", (paper_id,)).fetchone()
    return {"paper": paper_dict(paper), "note": row_to_dict(note)}


def delete_paper_response(paper_id: str) -> dict[str, Any]:
    with connect() as conn:
        paper = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not paper:
            raise RuntimeTaskError(404, "paper_not_found", "Paper not found.")
        vector_cleanup: list[dict[str, Any]] = []
        deleted_papers = delete_papers(conn, [paper_dict(paper)], vector_cleanup)
    return {"status": "deleted", "deleted_papers": deleted_papers, "vector_cleanup": vector_cleanup}


def paper_dict(row: Any) -> dict[str, Any]:
    return row_to_dict(row) or {}


def papers_with_notes(conn: Any, rows: list[Any]) -> list[dict[str, Any]]:
    papers = rows_to_dicts(rows)
    for paper in papers:
        note = conn.execute(
            "SELECT id, obsidian_path, created_at, updated_at FROM reading_notes WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1",
            (paper["id"],),
        ).fetchone()
        paper["latest_note"] = row_to_dict(note)
    return papers


def delete_papers(conn: Any, papers: list[dict[str, Any]], vector_cleanup_results: list[dict[str, Any]] | None = None) -> int:
    if not papers:
        return 0
    paper_ids = [paper["id"] for paper in papers]
    placeholders = ",".join("?" for _ in paper_ids)
    roots = [config.PAPER_DIR, config.PARSED_DIR, config.OBSIDIAN_VAULT_PATH, config.PDF_IMAGE_DIR, config.PDF_RENDERED_PAGE_DIR]
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
            safe_remove_path(path, roots)
    delete_paper_artifacts(conn, paper_ids)
    return len(paper_ids)


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
        paths.append(config.PDF_IMAGE_DIR / paper_id)
        paths.append(config.PDF_RENDERED_PAGE_DIR / paper_id)
    if note_path:
        paths.append(Path(note_path))
    return paths


def safe_remove_path(path: str | Path | None, roots: list[Path]) -> bool:
    if not path:
        return False
    try:
        target = Path(path).resolve()
        if not any(target.is_relative_to(root.resolve()) for root in roots):
            return False
        if target.is_file():
            target.unlink()
            return True
        if target.is_dir():
            shutil.rmtree(target)
            return True
    except OSError:
        return False
    return False


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
