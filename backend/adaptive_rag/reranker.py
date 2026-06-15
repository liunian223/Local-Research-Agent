from __future__ import annotations

import re
from typing import Any

from .abstract_policy import abstract_score_factor, is_abstract_item


def rerank(query: str, candidates: list[dict[str, Any]], query_analysis: dict[str, Any], final_top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    tokens = _tokens(query)
    target_sections = query_analysis.get("target_sections") or []
    for item in candidates:
        base = float(item.get("score") or 0.0)
        text = item.get("text") or ""
        section_text = f"{item.get('section_name', '')} {item.get('section_path', '')}".lower()
        metadata = item.get("metadata") or {}
        weight = float(item.get("retrieval_weight") or metadata.get("retrieval_weight") or (0.65 if is_abstract_item(item) else 1.0))
        lexical = sum(1.0 for token in tokens if token and token in text.lower())
        section_bonus = sum(4.0 for section in target_sections if section in section_text)
        source_bonus = 0.0
        if item.get("source_type") in {"table", "figure", "section_summary"}:
            source_bonus += 1.5
        score = (base + lexical + section_bonus + source_bonus) * weight
        score *= abstract_score_factor(item, query_analysis)
        if score > 0:
            updated = {**item, "final_score": score, "is_abstract": is_abstract_item(item)}
            scored.append((score, updated))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    final = [item for _, item in scored[:final_top_k]]
    for rank, item in enumerate(final, start=1):
        item["rank"] = rank
    return final, {
        "candidate_count": len(candidates),
        "final_count": len(final),
        "reranker": "rule_weighted_v1",
    }


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]{3,}|[\u4e00-\u9fff]{2,}", text.lower())
