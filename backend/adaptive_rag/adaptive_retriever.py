from __future__ import annotations

from typing import Any

import config
from structured_retriever import build_meta, collect_structured_scope_chunks, evidence_type_stats
from vector_store import VECTOR_STORE

from .evidence_checker import check_coverage
from .evidence_fusion import build_adaptive_evidence_bundle, dedupe_evidence, limit_abstract_evidence
from .hybrid_retriever import collect_candidates
from .query_analyzer import analyze_query
from .reranker import rerank


def adaptive_retrieve(conn: Any, scope: str, paper_id: str | None, query: str, top_k: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    top_k = top_k or config.RAG_TOP_K
    analysis = analyze_query(query, scope)
    analysis = {
        **analysis,
        "query_type": analysis.get("intent") or "unknown",
        "is_complex": analysis.get("complexity") == "complex",
        "scope": scope,
    }
    retrieval_mode = "complex_planned_retrieval" if analysis["complexity"] == "complex" else "simple_retrieve_rerank"
    if analysis.get("needs_page"):
        retrieval_mode = "page_lookup"
    elif analysis.get("needs_table"):
        retrieval_mode = "table_lookup"
    elif analysis.get("needs_figure"):
        retrieval_mode = "figure_lookup"
    elif scope == "global_library" and analysis["complexity"] == "complex":
        retrieval_mode = "global_structured_retrieval"

    candidate_top_k = config.RAG_SIMPLE_VECTOR_TOP_K if analysis["complexity"] == "simple" else config.RAG_COMPLEX_MAX_EVIDENCE * 3
    candidates, backend_meta = collect_candidates(conn, scope, paper_id, query, analysis, candidate_top_k)
    candidates = dedupe_evidence(candidates)
    final_top_k = config.RAG_SIMPLE_FINAL_TOP_K if analysis["complexity"] == "simple" else config.RAG_COMPLEX_MAX_EVIDENCE
    evidence, rerank_meta = rerank(query, candidates, analysis, final_top_k)

    abstract_limit = config.RAG_ABSTRACT_MAX_COMPLEX_EVIDENCE if analysis["complexity"] == "complex" else final_top_k
    evidence, abstract_counts = limit_abstract_evidence(evidence, abstract_limit)
    coverage = check_coverage(evidence, analysis)

    fallbacks: list[str] = []
    if backend_meta.get("fallback"):
        fallbacks.append("vector_retrieve_failed_local_keyword_used")
    if coverage.get("needs_second_pass"):
        second_pass = _second_pass(conn, scope, paper_id, query, analysis, coverage)
        if second_pass:
            merged, rerank_meta = rerank(query, dedupe_evidence(evidence + second_pass), analysis, final_top_k)
            evidence, abstract_counts = limit_abstract_evidence(merged, abstract_limit)
            coverage = check_coverage(evidence, analysis)
        if coverage.get("missing_sections"):
            fallbacks.append("complex_retrieval_missing_section_evidence")

    rows = collect_structured_scope_chunks(conn, scope, paper_id)
    meta = build_meta(
        {"mode": retrieval_mode, "intent": analysis.get("intent"), "section_hints": analysis.get("target_sections", [])},
        rows,
        evidence,
        backend_meta.get("backend") or "local_keyword",
        bool(backend_meta.get("fallback")),
        fallbacks,
    )
    meta.update(
        {
            "retrieval_mode": retrieval_mode,
            "legacy_mode": _legacy_mode(retrieval_mode, analysis),
            "query_analysis": analysis,
            "retrieval_plan": {
                "mode": retrieval_mode,
                "top_k": final_top_k,
                "candidate_top_k": candidate_top_k,
                "reason": _retrieval_reason(retrieval_mode, analysis),
                "sub_questions": analysis.get("sub_questions", []),
                "query_rewrites": analysis.get("query_rewrites", []),
                "coverage_requirements": {"target_sections": analysis.get("target_sections", [])},
            },
            "backend_diagnostics": {
                "configured_backend": VECTOR_STORE.backend_config().get("configured_backend"),
                "actual_backend": backend_meta.get("backend") or VECTOR_STORE.backend,
                "fallback_reason": backend_meta.get("fallback_reason") or VECTOR_STORE.backend_status().get("fallback_reason"),
                "exception_class": backend_meta.get("exception_class") or VECTOR_STORE.backend_status().get("exception_class"),
                "exception_message": backend_meta.get("error") or VECTOR_STORE.backend_status().get("exception_message"),
            },
            "fallback_reason": backend_meta.get("fallback_reason") or (VECTOR_STORE.backend_status().get("fallback_reason") if backend_meta.get("fallback") else ""),
            "retrieval_error": backend_meta.get("error") or "",
            "evidence_stats": evidence_type_stats(evidence),
            "abstract_control": {
                "has_abstract": _has_abstract(conn, paper_id),
                "abstract_mode": analysis.get("abstract_mode"),
                **abstract_counts,
                "abstract_penalty_applied": analysis.get("abstract_mode") == "downweight",
            },
            "rerank": rerank_meta,
            "coverage_check": coverage,
            "fallbacks": fallbacks,
        }
    )
    meta["evidence_bundle"] = build_adaptive_evidence_bundle(evidence, meta)
    return evidence, meta


def _retrieval_reason(mode: str, analysis: dict[str, Any]) -> str:
    if mode == "page_lookup":
        return "query asks for a page-specific answer"
    if mode == "table_lookup":
        return "query asks for table evidence"
    if mode == "figure_lookup":
        return "query asks for figure or caption evidence"
    if mode == "global_structured_retrieval":
        return "global library scope with a complex synthesis query"
    if mode == "complex_planned_retrieval":
        sections = ", ".join(analysis.get("target_sections") or [])
        return f"complex query requires section coverage{': ' + sections if sections else ''}"
    return "simple query can use hybrid retrieve and rerank"


def _second_pass(conn: Any, scope: str, paper_id: str | None, query: str, analysis: dict[str, Any], coverage: dict[str, Any]) -> list[dict[str, Any]]:
    extra: list[dict[str, Any]] = []
    for section in coverage.get("missing_sections") or []:
        section_query = f"{query} {section}"
        section_analysis = {**analysis, "target_sections": [section], "abstract_mode": "exclude"}
        candidates, _ = collect_candidates(conn, scope, paper_id, section_query, section_analysis, config.RAG_COMPLEX_SECTION_TOP_K * 3)
        extra.extend(candidates)
    return extra


def _legacy_mode(mode: str, analysis: dict[str, Any]) -> str:
    if mode == "simple_retrieve_rerank":
        return "simple_vector"
    if mode == "complex_planned_retrieval":
        return "complex_section_expansion"
    return mode


def _has_abstract(conn: Any, paper_id: str | None) -> bool:
    if not paper_id:
        row = conn.execute("SELECT 1 FROM document_chunks WHERE COALESCE(is_abstract, 0) = 1 LIMIT 1").fetchone()
    else:
        row = conn.execute("SELECT 1 FROM document_chunks WHERE paper_id = ? AND COALESCE(is_abstract, 0) = 1 LIMIT 1", (paper_id,)).fetchone()
    return bool(row)
