from __future__ import annotations

import json
import re
from typing import Any

import config
from database import rows_to_dicts
from vector_store import VECTOR_STORE


def retrieve_structured_evidence(conn: Any, scope: str, paper_id: str | None, query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if config.RAG_ADAPTIVE_ENABLED:
        from adaptive_rag.adaptive_retriever import adaptive_retrieve

        return adaptive_retrieve(conn, scope, paper_id, query, config.RAG_TOP_K)

    plan = plan_retrieval(query, scope)
    rows = collect_structured_scope_chunks(conn, scope, paper_id)
    fallbacks: list[str] = []

    if plan["mode"] == "page_lookup":
        evidence = retrieve_page(conn, paper_id, plan["page_number"])
        meta = build_meta(plan, rows, evidence, "structured_page", False, fallbacks)
        return evidence, meta
    if plan["mode"] == "table_lookup":
        direct = retrieve_table(conn, paper_id, query)
        if direct:
            meta = build_meta(plan, rows, direct, "structured_table", False, fallbacks)
            return direct, meta
    if plan["mode"] == "figure_lookup":
        direct = retrieve_figure(conn, paper_id, query)
        if direct:
            meta = build_meta(plan, rows, direct, "structured_figure", False, fallbacks)
            return direct, meta

    top_k = config.RAG_TOP_K
    if scope == "paper_and_note":
        paper_rows = [row for row in rows if row.get("source_type") != "note"]
        note_rows = [row for row in rows if row.get("source_type") == "note"]
        paper_ev, paper_meta = VECTOR_STORE.retrieve(query, paper_rows, 6)
        note_ev, note_meta = VECTOR_STORE.retrieve(query, note_rows, 4)
        evidence = rerank_with_intent(query, enrich_evidence(conn, paper_ev + note_ev))
        backend = paper_meta.get("backend") or note_meta.get("backend")
        fallback = bool(paper_meta.get("fallback") or note_meta.get("fallback"))
    elif plan["mode"] == "complex_section_expansion":
        expanded_rows = expand_rows_by_sections(rows, plan["section_hints"])
        evidence, vector_meta = VECTOR_STORE.retrieve(query, expanded_rows or rows, top_k)
        evidence = rerank_with_intent(query, enrich_evidence(conn, evidence))
        backend = vector_meta.get("backend")
        fallback = bool(vector_meta.get("fallback"))
    else:
        evidence, vector_meta = VECTOR_STORE.retrieve(query, rows, top_k)
        evidence = rerank_with_intent(query, enrich_evidence(conn, evidence))
        backend = vector_meta.get("backend")
        fallback = bool(vector_meta.get("fallback"))

    meta = build_meta(plan, rows, evidence, backend or "local_keyword", fallback, fallbacks)
    if fallback:
        meta["keyword_fallback_used"] = True
    return evidence, meta


def collect_structured_scope_chunks(conn: Any, scope: str, paper_id: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if scope in {"paper_only", "paper_and_note"}:
        if paper_id:
            paper_rows = conn.execute("SELECT * FROM paper_chunks WHERE paper_id = ?", (paper_id,)).fetchall()
        else:
            paper_rows = conn.execute("SELECT * FROM paper_chunks").fetchall()
        rows.extend(_normalize_paper_rows(rows_to_dicts(paper_rows)))
    if scope in {"note_only", "paper_and_note"}:
        if paper_id:
            note_rows = conn.execute("SELECT * FROM note_chunks WHERE paper_id = ?", (paper_id,)).fetchall()
        else:
            note_rows = conn.execute("SELECT * FROM note_chunks").fetchall()
        rows.extend(_normalize_note_rows(rows_to_dicts(note_rows)))
    if scope == "global_library":
        rows.extend(_normalize_paper_rows(rows_to_dicts(conn.execute("SELECT * FROM paper_chunks").fetchall())))
        rows.extend(_normalize_note_rows(rows_to_dicts(conn.execute("SELECT * FROM note_chunks").fetchall())))
    return rows


def plan_retrieval(query: str, scope: str) -> dict[str, Any]:
    lowered = query.lower()
    page_number = extract_page_number(query)
    if page_number:
        return {"mode": "page_lookup", "intent": "page_question", "page_number": page_number, "section_hints": []}
    if re.search(r"\b(table|tab\.)\s*\d+|表\s*\d+", query, re.I):
        return {"mode": "table_lookup", "intent": "table_question", "page_number": None, "section_hints": []}
    if re.search(r"\b(fig\.?|figure)\s*\d+|图\s*\d+", query, re.I):
        return {"mode": "figure_lookup", "intent": "figure_question", "page_number": None, "section_hints": []}
    hints = section_hints(query)
    if scope == "global_library":
        return {"mode": "global_structured_retrieval", "intent": "global_question", "page_number": None, "section_hints": hints}
    if hints or any(token in lowered for token in ["how", "why", "compare", "explain", "method", "experiment", "result"]):
        return {"mode": "complex_section_expansion", "intent": "_".join(hints) or "complex_question", "page_number": None, "section_hints": hints}
    return {"mode": "simple_vector", "intent": "simple_question", "page_number": None, "section_hints": []}


def retrieve_page(conn: Any, paper_id: str | None, page_number: int | None) -> list[dict[str, Any]]:
    if not page_number:
        return []
    if paper_id:
        rows = conn.execute("SELECT * FROM document_pages WHERE paper_id = ? AND page_number = ?", (paper_id, page_number)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM document_pages WHERE page_number = ?", (page_number,)).fetchall()
    evidence = []
    for rank, row in enumerate(rows_to_dicts(rows), start=1):
        text = row.get("main_text") or ""
        evidence.append(
            {
                "rank": rank,
                "score": 1.0,
                "source_type": "page_summary",
                "paper_id": row.get("paper_id"),
                "chunk_id": row.get("id"),
                "section_name": f"Page {row.get('page_number')}",
                "section_path": f"Page {row.get('page_number')}",
                "page_start": row.get("page_number"),
                "page_end": row.get("page_number"),
                "text": text[: config.MAX_EVIDENCE_CHARS],
                "context_prefix": f"Page {row.get('page_number')} of paper {row.get('paper_id')}",
                "metadata": _loads(row.get("metadata_json")),
            }
        )
    return evidence


def retrieve_table(conn: Any, paper_id: str | None, query: str) -> list[dict[str, Any]]:
    number = extract_source_number(query)
    if paper_id and number:
        rows = conn.execute("SELECT * FROM document_tables WHERE paper_id = ? ORDER BY page_number ASC", (paper_id,)).fetchall()
    elif paper_id:
        rows = conn.execute("SELECT * FROM document_tables WHERE paper_id = ? ORDER BY page_number ASC", (paper_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM document_tables ORDER BY page_number ASC").fetchall()
    selected = _select_numbered(rows_to_dicts(rows), "table_id", number)
    return [_table_to_evidence(row, idx) for idx, row in enumerate(selected, start=1)]


def retrieve_figure(conn: Any, paper_id: str | None, query: str) -> list[dict[str, Any]]:
    number = extract_source_number(query)
    if paper_id:
        rows = conn.execute("SELECT * FROM document_figures WHERE paper_id = ? ORDER BY page_number ASC", (paper_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM document_figures ORDER BY page_number ASC").fetchall()
    selected = _select_numbered(rows_to_dicts(rows), "figure_id", number)
    return [_figure_to_evidence(row, idx) for idx, row in enumerate(selected, start=1)]


def enrich_evidence(conn: Any, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for item in evidence:
        chunk_id = item.get("chunk_id")
        row = None
        if chunk_id:
            row = conn.execute("SELECT * FROM paper_chunks WHERE id = ?", (chunk_id,)).fetchone()
        if row:
            data = dict(row)
            metadata = _loads(data.get("metadata_json"))
            enriched.append(
                {
                    **item,
                    "source_type": data.get("source_type") or item.get("source_type") or "text",
                    "section_name": data.get("section_name") or item.get("section_name") or "Body",
                    "section_path": data.get("section_path") or metadata.get("section_path") or item.get("section_path") or data.get("section_name") or "Body",
                    "page_start": data.get("page_start") or metadata.get("page_start"),
                    "page_end": data.get("page_end") or metadata.get("page_end"),
                    "context_prefix": data.get("context_prefix") or metadata.get("context_prefix") or "",
                    "is_abstract": bool(data.get("is_abstract") or metadata.get("is_abstract")),
                    "retrieval_weight": data.get("retrieval_weight") or metadata.get("retrieval_weight") or 1.0,
                    "chunk_role": data.get("chunk_role") or metadata.get("chunk_role") or "",
                    "section_role": data.get("section_role") or metadata.get("section_role") or "",
                    "metadata": metadata,
                }
            )
        else:
            enriched.append(item)
    return enriched


def build_evidence_bundle(evidence: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    bundle = {
        "text_chunks": [],
        "section_summaries": [],
        "abstract_chunks": [],
        "tables": [],
        "figures": [],
        "pages": [],
        "fallbacks": meta.get("fallbacks", []),
        "warnings": [],
    }
    if meta.get("evidence_bundle"):
        return meta["evidence_bundle"]
    for item in evidence:
        source_type = item.get("source_type") or "text"
        metadata = item.get("metadata") or {}
        is_abstract = bool(item.get("is_abstract") or metadata.get("is_abstract")) or str(item.get("chunk_role") or metadata.get("chunk_role") or "").lower() == "abstract"
        if is_abstract:
            bundle["abstract_chunks"].append(item)
        elif source_type == "section_summary":
            bundle["section_summaries"].append(item)
        elif source_type == "table":
            bundle["tables"].append(item)
        elif source_type == "figure":
            bundle["figures"].append(item)
        elif source_type == "page_summary":
            bundle["pages"].append(item)
        else:
            bundle["text_chunks"].append(item)
    return bundle


def rag_pipeline_summary(conn: Any, paper_id: str | None = None) -> dict[str, Any]:
    where = "WHERE paper_id = ?" if paper_id else ""
    params = (paper_id,) if paper_id else ()
    def count(table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) AS count FROM {table} {where}", params).fetchone()["count"])

    text_chunk_count = int(
        conn.execute(
            f"SELECT COUNT(*) AS count FROM paper_chunks {where} {'AND' if where else 'WHERE'} COALESCE(source_type, 'text') IN ('text', 'section_summary')",
            params,
        ).fetchone()["count"]
    )
    return {
        "parser_version": config.LAYOUT_RAG_PARSER_VERSION,
        "chunk_strategy": "semantic_layout",
        "vector_backend": VECTOR_STORE.backend,
        "keyword_fallback_used": VECTOR_STORE.collection is None,
        "backend_config": VECTOR_STORE.backend_config(),
        "backend_status": VECTOR_STORE.backend_status(),
        "page_count": count("document_pages"),
        "section_count": count("document_sections"),
        "text_chunk_count": text_chunk_count,
        "table_count": count("document_tables"),
        "figure_count": count("document_figures"),
        "table_chunk_count": _count_chunks(conn, "table", paper_id),
        "figure_chunk_count": _count_chunks(conn, "figure", paper_id),
    }


def build_meta(plan: dict[str, Any], rows: list[dict[str, Any]], evidence: list[dict[str, Any]], backend: str, fallback: bool, fallbacks: list[str]) -> dict[str, Any]:
    retrieved_sections = sorted({item.get("section_path") or item.get("section_name") for item in evidence if item.get("section_path") or item.get("section_name")})
    retrieved_tables = sorted({table_id for item in evidence for table_id in _metadata_list(item, "table_ids")})
    retrieved_figures = sorted({figure_id for item in evidence for figure_id in _metadata_list(item, "figure_ids")})
    pages = sorted({page for item in evidence for page in [item.get("page_start"), item.get("page_end")] if page})
    backend_status = VECTOR_STORE.backend_status()
    return {
        "backend": backend,
        "backend_status": backend_status,
        "backend_config": VECTOR_STORE.backend_config(),
        "backend_diagnostics": {
            "configured_backend": backend_status.get("configured_backend"),
            "actual_backend": backend,
            "fallback_reason": backend_status.get("fallback_reason"),
            "exception_class": backend_status.get("exception_class"),
            "exception_message": backend_status.get("exception_message"),
        },
        "fallback": fallback,
        "fallback_reason": backend_status.get("fallback_reason") if fallback else "",
        "keyword_fallback_used": fallback or backend == "local_keyword",
        "retrieval_mode": plan.get("mode"),
        "retrieval_intent": plan.get("intent"),
        "retrieved_sections": retrieved_sections,
        "retrieved_tables": retrieved_tables,
        "retrieved_figures": retrieved_figures,
        "retrieved_pages": pages,
        "candidate_count": len(rows),
        "evidence_stats": evidence_type_stats(evidence),
        "fallbacks": fallbacks,
    }


def evidence_type_stats(evidence: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "text_chunks": 0,
        "section_summaries": 0,
        "abstract_chunks": 0,
        "tables": 0,
        "figures": 0,
        "pages": 0,
    }
    for item in evidence:
        source_type = item.get("source_type") or "text"
        metadata = item.get("metadata") or {}
        is_abstract = bool(item.get("is_abstract") or metadata.get("is_abstract")) or str(item.get("chunk_role") or metadata.get("chunk_role") or "").lower() == "abstract"
        if is_abstract:
            stats["abstract_chunks"] += 1
        elif source_type == "section_summary":
            stats["section_summaries"] += 1
        elif source_type == "table":
            stats["tables"] += 1
        elif source_type == "figure":
            stats["figures"] += 1
        elif source_type == "page_summary":
            stats["pages"] += 1
        else:
            stats["text_chunks"] += 1
    return stats


def rerank_with_intent(query: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints = section_hints(query)
    if not hints:
        return evidence
    scored = []
    for item in evidence:
        section = f"{item.get('section_name', '')} {item.get('section_path', '')}".lower()
        source_bonus = 2 if item.get("source_type") in {"section_summary", "table", "figure"} else 0
        hint_bonus = sum(4 for hint in hints if hint in section)
        scored.append((hint_bonus + source_bonus, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    reranked = [item for _, item in scored]
    for rank, item in enumerate(reranked, start=1):
        item["rank"] = rank
    return reranked


def expand_rows_by_sections(rows: list[dict[str, Any]], hints: list[str]) -> list[dict[str, Any]]:
    if not hints:
        return rows
    matched = [
        row
        for row in rows
        if any(hint in f"{row.get('section_name', '')} {row.get('section_path', '')}".lower() for hint in hints)
        or row.get("source_type") == "section_summary"
    ]
    return matched or rows


def section_hints(query: str) -> list[str]:
    lowered = query.lower()
    hints = []
    mapping = {
        "method": ["method", "approach", "model", "framework", "方法", "模型", "框架"],
        "experiment": ["experiment", "evaluation", "实验", "评测"],
        "result": ["result", "结果"],
        "conclusion": ["conclusion", "结论"],
        "introduction": ["introduction", "背景", "引言"],
    }
    for key, tokens in mapping.items():
        if any(token in lowered or token in query for token in tokens):
            hints.append(key)
    return hints


def extract_page_number(query: str) -> int | None:
    match = re.search(r"(?:page|p\.|第)\s*(\d+)\s*(?:页)?", query, re.I)
    return int(match.group(1)) if match else None


def extract_source_number(query: str) -> int | None:
    match = re.search(r"(?:table|tab\.|figure|fig\.|图|表)\s*(\d+)", query, re.I)
    return int(match.group(1)) if match else None


def _normalize_paper_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        source_type = row.get("source_type") or "text"
        normalized.append(
            {
                **row,
                "source_type": source_type,
                "text": row.get("text") or "",
                "section_name": row.get("section_name") or row.get("section_path") or "Body",
                "is_abstract": bool(row.get("is_abstract")),
                "retrieval_weight": row.get("retrieval_weight") or 1.0,
                "chunk_role": row.get("chunk_role") or "",
                "section_role": row.get("section_role") or "",
            }
        )
    return normalized


def _normalize_note_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "source_type": "note",
            "section_name": row.get("section_name") or "Note",
            "is_abstract": False,
            "retrieval_weight": 1.0,
            "chunk_role": "note",
            "section_role": "note",
        }
        for row in rows
    ]


def _select_numbered(rows: list[dict[str, Any]], id_key: str, number: int | None) -> list[dict[str, Any]]:
    if not number:
        return rows[: config.RAG_TOP_K]
    suffix = f"_{number:03d}"
    selected = [row for row in rows if str(row.get(id_key, "")).endswith(suffix)]
    return selected or rows[:1]


def _table_to_evidence(row: dict[str, Any], rank: int) -> dict[str, Any]:
    text = "\n\n".join(part for part in [row.get("caption"), row.get("summary"), row.get("structured_text"), row.get("nearby_text")] if part)
    metadata = {**_loads(row.get("metadata_json")), "table_ids": [row.get("id")]}
    return {
        "rank": rank,
        "score": 1.0,
        "source_type": "table",
        "paper_id": row.get("paper_id"),
        "chunk_id": row.get("id"),
        "section_name": row.get("section_path") or "Table",
        "section_path": row.get("section_path") or "Table",
        "page_start": row.get("page_number"),
        "page_end": row.get("page_number"),
        "text": text[: config.MAX_EVIDENCE_CHARS],
        "context_prefix": f"Table evidence on page {row.get('page_number')}: {row.get('caption') or ''}",
        "metadata": metadata,
    }


def _figure_to_evidence(row: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata_json = _loads(row.get("metadata_json"))
    image_path = row.get("image_path") or metadata_json.get("image_path") or ""
    page_image_path = metadata_json.get("page_image_path") or ""
    text = "\n\n".join(
        part
        for part in [
            row.get("caption"),
            row.get("visual_summary"),
            row.get("nearby_text"),
            f"figure_image_path: {image_path}" if image_path else "",
            f"page_image_path: {page_image_path}" if page_image_path else "",
        ]
        if part
    )
    metadata = {
        **metadata_json,
        "figure_ids": [row.get("id")],
        "image_path": image_path,
        "page_image_path": page_image_path,
    }
    return {
        "rank": rank,
        "score": 1.0,
        "source_type": "figure",
        "paper_id": row.get("paper_id"),
        "chunk_id": row.get("id"),
        "section_name": row.get("section_path") or "Figure",
        "section_path": row.get("section_path") or "Figure",
        "page_start": row.get("page_number"),
        "page_end": row.get("page_number"),
        "text": text[: config.MAX_EVIDENCE_CHARS],
        "context_prefix": f"Figure evidence on page {row.get('page_number')}: {row.get('caption') or ''}",
        "metadata": metadata,
    }


def _metadata_list(item: dict[str, Any], key: str) -> list[str]:
    metadata = item.get("metadata") or {}
    values = metadata.get(key) or []
    return [value for value in values if value]


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _count_chunks(conn: Any, source_type: str, paper_id: str | None) -> int:
    if paper_id:
        row = conn.execute("SELECT COUNT(*) AS count FROM paper_chunks WHERE paper_id = ? AND source_type = ?", (paper_id, source_type)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS count FROM paper_chunks WHERE source_type = ?", (source_type,)).fetchone()
    return int(row["count"])
