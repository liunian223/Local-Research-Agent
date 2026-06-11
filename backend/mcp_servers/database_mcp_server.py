from __future__ import annotations

from typing import Any

from database import rows_to_dicts


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
