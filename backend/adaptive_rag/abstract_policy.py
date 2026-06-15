from __future__ import annotations

from enum import Enum
from typing import Any

import config


class AbstractMode(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    DOWNWEIGHT = "downweight"
    ONLY = "only"


def decide_abstract_mode(query: str, analysis: dict[str, Any]) -> str:
    intent = analysis.get("intent") or "unknown"
    if intent == "metadata":
        return AbstractMode.EXCLUDE.value
    if intent in {"summary", "abstract"}:
        return AbstractMode.INCLUDE.value
    if intent in {"method", "experiment", "result", "table", "figure", "page", "reproduction"}:
        return AbstractMode.DOWNWEIGHT.value
    if analysis.get("complexity") == "complex":
        return AbstractMode.DOWNWEIGHT.value
    return config.RAG_ABSTRACT_DEFAULT_MODE


def abstract_score_factor(item: dict[str, Any], query_analysis: dict[str, Any]) -> float:
    if not is_abstract_item(item):
        return 1.0
    mode = query_analysis.get("abstract_mode") or config.RAG_ABSTRACT_DEFAULT_MODE
    intent = query_analysis.get("intent") or "unknown"
    if mode == AbstractMode.EXCLUDE.value:
        return 0.0
    if mode == AbstractMode.ONLY.value:
        return 1.2
    if intent in {"summary", "abstract"}:
        return 1.15
    if mode == AbstractMode.DOWNWEIGHT.value:
        if intent in {"method", "experiment", "result", "reproduction"}:
            return min(config.RAG_ABSTRACT_DOWNWEIGHT_FACTOR, 0.55)
        return config.RAG_ABSTRACT_DOWNWEIGHT_FACTOR
    return 1.0


def is_abstract_item(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") or {}
    if bool(item.get("is_abstract")) or bool(metadata.get("is_abstract")):
        return True
    role = str(item.get("chunk_role") or item.get("section_role") or metadata.get("chunk_role") or metadata.get("section_role") or "").lower()
    if role == "abstract":
        return True
    section = f"{item.get('section_name', '')} {item.get('section_path', '')}".lower()
    return section.strip() in {"abstract", "summary"}
