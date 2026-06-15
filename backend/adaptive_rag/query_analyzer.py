from __future__ import annotations

import re
from typing import Any

from .abstract_policy import decide_abstract_mode


COMPLEX_KEYWORDS = [
    "why",
    "how",
    "explain",
    "evaluate",
    "critique",
    "compare",
    "comparison",
    "trade-off",
    "limitation",
    "limitations",
    "reproduce",
    "reproduction",
    "replicate",
    "relationship",
    "synthesize",
    "across papers",
    "global library",
    "为什么",
    "如何评价",
    "是否",
    "值得复现",
    "创新点",
    "局限",
    "优缺点",
    "对比",
    "比较",
    "结合",
    "分析",
    "启发",
    "改进",
    "复现",
    "全知识库",
    "多篇",
    "关系",
]

INTENT_KEYWORDS = {
    "metadata": ["doi", "author", "authors", "title", "year", "作者", "年份", "题目", "标题"],
    "summary": ["summary", "summarize", "main idea", "what is this paper about", "主要讲", "主要研究", "总结", "概括"],
    "abstract": ["abstract", "摘要"],
    "method": ["method", "methodology", "approach", "model", "algorithm", "framework", "方法", "模型", "算法", "框架"],
    "experiment": ["experiment", "evaluation", "setup", "dataset", "baseline", "实验", "评测", "数据集", "设置"],
    "result": ["result", "performance", "metric", "accuracy", "结果", "指标", "性能"],
    "table": ["table", "tab.", "表"],
    "figure": ["figure", "fig.", "图"],
    "page": ["page", "p.", "页"],
    "comparison": ["compare", "comparison", "versus", "对比", "比较"],
    "reproduction": ["reproduce", "replicate", "复现", "值得复现"],
    "critique": ["critique", "limitation", "weakness", "局限", "不足", "优缺点", "评价"],
    "global_synthesis": ["global library", "knowledge base", "all papers", "全知识库", "知识库", "多篇"],
}

SECTION_BY_INTENT = {
    "method": ["method"],
    "experiment": ["experiment"],
    "result": ["result"],
    "reproduction": ["method", "experiment", "result"],
    "critique": ["method", "experiment", "result", "discussion", "conclusion"],
    "comparison": ["method", "experiment", "result"],
    "summary": ["abstract", "introduction", "conclusion"],
}


def analyze_query(query: str, chat_scope: str = "paper_only") -> dict[str, Any]:
    text = query or ""
    lowered = text.lower()
    intent = _intent(text, lowered, chat_scope)
    target_sections = SECTION_BY_INTENT.get(intent, [])
    needs_table = intent == "table" or bool(re.search(r"\b(table|tab\.)\s*\d+|表\s*\d+", text, re.I))
    needs_figure = intent == "figure" or bool(re.search(r"\b(fig\.?|figure)\s*\d+|图\s*\d+", text, re.I))
    needs_page = intent == "page" or bool(re.search(r"(?:page|p\.)\s*\d+|第\s*\d+\s*页", text, re.I))
    complexity = _complexity(text, lowered, chat_scope, intent)
    needs_decomposition = complexity == "complex"
    analysis: dict[str, Any] = {
        "complexity": complexity,
        "intent": intent,
        "target_sections": target_sections,
        "needs_decomposition": needs_decomposition,
        "needs_table": needs_table,
        "needs_figure": needs_figure,
        "needs_page": needs_page,
        "query_rewrites": _query_rewrites(text, intent, target_sections),
        "sub_questions": _sub_questions(text, intent, target_sections) if needs_decomposition else [],
    }
    analysis["abstract_mode"] = decide_abstract_mode(text, analysis)
    return analysis


def _intent(text: str, lowered: str, chat_scope: str) -> str:
    if chat_scope == "global_library" and any(token in lowered or token in text for token in INTENT_KEYWORDS["global_synthesis"]):
        return "global_synthesis"
    for intent, tokens in INTENT_KEYWORDS.items():
        if any(token in lowered or token in text for token in tokens):
            return intent
    return "unknown"


def _complexity(text: str, lowered: str, chat_scope: str, intent: str) -> str:
    if chat_scope == "global_library" and intent in {"global_synthesis", "comparison", "unknown"}:
        return "complex"
    if intent in {"comparison", "reproduction", "critique", "global_synthesis"}:
        return "complex"
    if any(token in lowered or token in text for token in COMPLEX_KEYWORDS):
        return "complex"
    if text.count("？") + text.count("?") > 1:
        return "complex"
    if any(token in text for token in ["并且", "同时", "以及", "结合"]) or any(token in lowered for token in [" and ", " as well as ", " together with "]):
        return "complex"
    return "simple"


def _query_rewrites(query: str, intent: str, sections: list[str]) -> list[str]:
    rewrites = [query]
    if sections:
        rewrites.extend(f"{query} {section}" for section in sections)
    if intent == "summary":
        rewrites.append(f"{query} abstract introduction conclusion")
    return list(dict.fromkeys(item.strip() for item in rewrites if item.strip()))


def _sub_questions(query: str, intent: str, sections: list[str]) -> list[str]:
    if intent == "reproduction":
        return [
            f"What method details support reproduction? {query}",
            f"What experimental setup and datasets are reported? {query}",
            f"What results or limitations affect reproducibility? {query}",
        ]
    if sections:
        return [f"Find {section} evidence for: {query}" for section in sections]
    return [
        f"Identify the paper's direct evidence for: {query}",
        f"Find supporting or missing evidence for: {query}",
    ]
