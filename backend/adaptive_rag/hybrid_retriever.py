from __future__ import annotations

from typing import Any

from rag import score_chunks
from structured_retriever import (
    collect_structured_scope_chunks,
    enrich_evidence,
    retrieve_figure,
    retrieve_page,
    retrieve_table,
)
from vector_store import VECTOR_STORE


def collect_candidates(conn: Any, scope: str, paper_id: str | None, query: str, query_analysis: dict[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if query_analysis.get("needs_page"):
        page = _extract_page(query)
        direct = retrieve_page(conn, paper_id, page)
        return direct, {"backend": "structured_page", "fallback": False, "candidate_count": len(direct)}
    if query_analysis.get("needs_table"):
        direct = retrieve_table(conn, paper_id, query)
        if direct:
            return direct, {"backend": "structured_table", "fallback": False, "candidate_count": len(direct)}
    if query_analysis.get("needs_figure"):
        direct = retrieve_figure(conn, paper_id, query)
        if direct:
            return direct, {"backend": "structured_figure", "fallback": False, "candidate_count": len(direct)}

    rows = collect_structured_scope_chunks(conn, scope, paper_id)
    rows = _filter_by_abstract_mode(rows, query_analysis)
    vector_ev, vector_meta = VECTOR_STORE.retrieve(query, rows, top_k)
    keyword_ev = score_chunks(query, rows, top_k)
    candidates = enrich_evidence(conn, vector_ev + keyword_ev)
    return candidates, {
        "backend": vector_meta.get("backend") or VECTOR_STORE.backend,
        "fallback": bool(vector_meta.get("fallback")),
        "error": vector_meta.get("error"),
        "candidate_count": len(rows),
    }


def _filter_by_abstract_mode(rows: list[dict[str, Any]], query_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    mode = query_analysis.get("abstract_mode")
    if mode not in {"exclude", "only"}:
        return rows
    filtered = []
    for row in rows:
        is_abstract = bool(row.get("is_abstract")) or "abstract" in f"{row.get('section_name', '')} {row.get('section_path', '')}".lower()
        if mode == "exclude" and not is_abstract:
            filtered.append(row)
        elif mode == "only" and is_abstract:
            filtered.append(row)
    return filtered or rows


def _extract_page(query: str) -> int | None:
    from structured_retriever import extract_page_number

    return extract_page_number(query)
