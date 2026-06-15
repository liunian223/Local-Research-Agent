from __future__ import annotations

from typing import Any

from .abstract_policy import is_abstract_item


def dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = item.get("chunk_id") or item.get("id") or (item.get("text") or "")[:120]
        if key in seen:
            continue
        seen.add(str(key))
        unique.append(item)
    return unique


def build_adaptive_evidence_bundle(evidence: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    bundle = {
        "text_chunks": [],
        "section_summaries": [],
        "abstract_chunks": [],
        "tables": [],
        "figures": [],
        "pages": [],
        "fallbacks": meta.get("fallbacks", []),
        "warnings": list(meta.get("warnings", [])),
    }
    for item in evidence:
        source_type = item.get("source_type") or "text"
        if is_abstract_item(item):
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


def limit_abstract_evidence(evidence: list[dict[str, Any]], max_abstract: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    used = 0
    final: list[dict[str, Any]] = []
    recalled = 0
    for item in evidence:
        if is_abstract_item(item):
            recalled += 1
            if used >= max_abstract:
                continue
            used += 1
        final.append(item)
    for rank, item in enumerate(final, start=1):
        item["rank"] = rank
    return final, {"abstract_chunks_recalled": recalled, "abstract_chunks_used": used}
