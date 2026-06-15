from __future__ import annotations

from typing import Any

from .abstract_policy import is_abstract_item


def check_coverage(evidence: list[dict[str, Any]], query_analysis: dict[str, Any]) -> dict[str, Any]:
    required = query_analysis.get("target_sections") or []
    covered: dict[str, bool] = {}
    for section in required:
        covered[section] = any(_matches_section(item, section) for item in evidence if not is_abstract_item(item))
    missing = [section for section, ok in covered.items() if not ok]
    return {
        "sufficient": not missing,
        "covered_sections": covered,
        "missing_sections": missing,
        "needs_second_pass": bool(missing and query_analysis.get("complexity") == "complex"),
    }


def _matches_section(item: dict[str, Any], section: str) -> bool:
    source = f"{item.get('section_name', '')} {item.get('section_path', '')} {item.get('context_prefix', '')}".lower()
    if section == "experiment":
        return any(token in source for token in ["experiment", "evaluation", "dataset", "实验", "评测"])
    if section == "method":
        return any(token in source for token in ["method", "approach", "model", "framework", "方法", "模型"])
    if section == "result":
        return any(token in source for token in ["result", "performance", "metric", "结果", "指标"])
    return section in source
