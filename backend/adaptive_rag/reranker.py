from __future__ import annotations

import re
from typing import Any

from .abstract_policy import abstract_score_factor, is_abstract_item


def rerank(query: str, candidates: list[dict[str, Any]], query_analysis: dict[str, Any], final_top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    tokens = _tokens(query)
    target_sections = query_analysis.get("target_sections") or []
    weights = _weights_for_intent(query_analysis)
    for item in candidates:
        base = float(item.get("score") or 0.0)
        text = item.get("text") or ""
        section_text = f"{item.get('section_name', '')} {item.get('section_path', '')}".lower()
        metadata = item.get("metadata") or {}
        weight = float(item.get("retrieval_weight") or metadata.get("retrieval_weight") or (0.65 if is_abstract_item(item) else 1.0))
        lexical = sum(1.0 for token in tokens if token and token in text.lower())
        section_bonus = _section_bonus(section_text, target_sections, query_analysis, weights)
        source_type = item.get("source_type") or "text"
        table_bonus = weights["table_bonus"] if source_type == "table" else 0.0
        figure_bonus = weights["figure_bonus"] if source_type == "figure" else 0.0
        page_bonus = weights["page_bonus"] if source_type == "page_summary" else 0.0
        summary_bonus = weights["section_summary_bonus"] if source_type == "section_summary" else 0.0
        raw_score = base + lexical + section_bonus + table_bonus + figure_bonus + page_bonus + summary_bonus
        abstract_factor = abstract_score_factor(item, query_analysis)
        score = raw_score * weight * abstract_factor
        if score > 0:
            breakdown = {
                "base_score": round(base, 4),
                "lexical_hit_score": round(lexical, 4),
                "section_bonus": round(section_bonus, 4),
                "table_bonus": round(table_bonus, 4),
                "figure_bonus": round(figure_bonus, 4),
                "page_bonus": round(page_bonus, 4),
                "section_summary_bonus": round(summary_bonus, 4),
                "retrieval_weight": round(weight, 4),
                "abstract_penalty": round(abstract_factor, 4),
                "final_score": round(score, 4),
            }
            updated = {**item, "final_score": score, "score_breakdown": breakdown, "is_abstract": is_abstract_item(item)}
            scored.append((score, updated))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    final = [item for _, item in scored[:final_top_k]]
    for rank, item in enumerate(final, start=1):
        item["rank"] = rank
    return final, {
        "candidate_count": len(candidates),
        "final_count": len(final),
        "reranker": "rule_weighted_v1",
        "weight_rules": weights,
        "score_breakdown_available": True,
    }


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]{3,}|[\u4e00-\u9fff]{2,}", text.lower())


def _weights_for_intent(query_analysis: dict[str, Any]) -> dict[str, float]:
    intent = query_analysis.get("intent") or "unknown"
    weights = {
        "target_section_bonus": 4.0,
        "method_section_bonus": 2.0,
        "experiment_section_bonus": 2.0,
        "result_section_bonus": 2.0,
        "conclusion_section_bonus": 1.5,
        "section_summary_bonus": 1.5,
        "table_bonus": 1.5,
        "figure_bonus": 1.5,
        "page_bonus": 1.0,
    }
    if intent == "method":
        weights.update({"target_section_bonus": 5.5, "method_section_bonus": 4.5})
    elif intent in {"experiment", "result"}:
        weights.update({"target_section_bonus": 5.0, "experiment_section_bonus": 4.0, "result_section_bonus": 4.0})
    elif intent == "table":
        weights.update({"table_bonus": 5.0, "section_summary_bonus": 1.0})
    elif intent == "figure":
        weights.update({"figure_bonus": 5.0, "section_summary_bonus": 1.0})
    elif intent == "summary":
        weights.update({"section_summary_bonus": 3.0, "conclusion_section_bonus": 2.5})
    elif intent in {"comparison", "reproduction", "critique"}:
        weights.update({"target_section_bonus": 5.0, "method_section_bonus": 3.5, "experiment_section_bonus": 3.5, "result_section_bonus": 3.5})
    return weights


def _section_bonus(section_text: str, target_sections: list[str], query_analysis: dict[str, Any], weights: dict[str, float]) -> float:
    bonus = sum(weights["target_section_bonus"] for section in target_sections if section and section in section_text)
    if any(token in section_text for token in ["method", "approach", "model", "framework", "方法", "模型"]):
        bonus += weights["method_section_bonus"]
    if any(token in section_text for token in ["experiment", "evaluation", "dataset", "实验", "评测"]):
        bonus += weights["experiment_section_bonus"]
    if any(token in section_text for token in ["result", "performance", "metric", "结果", "指标"]):
        bonus += weights["result_section_bonus"]
    if any(token in section_text for token in ["conclusion", "discussion", "结论", "讨论"]):
        bonus += weights["conclusion_section_bonus"]
    if query_analysis.get("intent") == "summary" and "abstract" in section_text:
        bonus += 0.5
    return bonus
