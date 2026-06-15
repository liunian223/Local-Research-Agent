from __future__ import annotations

import re
from typing import Any


ABSTRACT_HEADINGS = {"abstract", "summary", "摘要", "中文摘要", "内容摘要", "英文摘要"}
ABSTRACT_EXCLUDE_HEADINGS = {"graphical abstract", "author summary", "plain language summary", "highlights", "keywords", "关键字", "关键词"}
ABSTRACT_END_RE = re.compile(
    r"^(keywords?|key words|index terms|关键词|关键字|1\s+introduction|1\.?\s*introduction|i\.?\s*introduction|introduction|引言|绪论|1\s*引言)\b",
    re.I,
)
ABSTRACT_INLINE_END_RE = re.compile(
    r"\b(keywords?|key words|index terms)\s*[:：]|(关键词|关键字)\s*[:：]|\b(1\s+introduction|1\.?\s*introduction|i\.?\s*introduction|introduction)\b|(?:^|\s)(引言|绪论|1\s*引言)\b",
    re.I,
)


def detect_abstract(document: dict[str, Any]) -> dict[str, Any]:
    sections = document.get("sections") or []
    blocks = document.get("text_blocks") or []
    block_by_id = {block.get("block_id"): block for block in blocks}

    for section in sections:
        title = _clean_heading(section.get("title") or section.get("normalized_name") or "")
        if _is_abstract_heading(title):
            result = _result_from_section(section, block_by_id, "heading_rule", 0.9)
            _mark_document(document, result)
            return result

    result = _detect_from_first_page(document)
    _mark_document(document, result)
    return result


def _result_from_section(section: dict[str, Any], block_by_id: dict[str, dict[str, Any]], boundary_source: str, confidence: float) -> dict[str, Any]:
    selected_blocks = []
    for block_id in section.get("block_ids") or []:
        block = block_by_id.get(block_id)
        if not block or block.get("is_header") or block.get("is_footer"):
            continue
        text = block.get("text") or ""
        first = text.splitlines()[0].strip() if text.splitlines() else ""
        if first and _is_end_heading(first):
            break
        selected_blocks.append(block)
    abstract_text = _clean_abstract_text("\n\n".join(block.get("text", "") for block in selected_blocks))
    return {
        "has_abstract": bool(abstract_text),
        "abstract_text": abstract_text,
        "page_start": min((block.get("page_number") for block in selected_blocks if block.get("page_number")), default=section.get("page_start")),
        "page_end": max((block.get("page_number") for block in selected_blocks if block.get("page_number")), default=section.get("page_end")),
        "block_ids": [block.get("block_id") for block in selected_blocks if block.get("block_id")],
        "section_id": section.get("section_id") or "",
        "boundary_source": boundary_source,
        "confidence": confidence if abstract_text else 0.0,
        "warnings": [] if abstract_text else ["No reliable abstract boundary found."],
    }


def _detect_from_first_page(document: dict[str, Any]) -> dict[str, Any]:
    blocks = [
        block
        for block in document.get("text_blocks") or []
        if (block.get("page_number") or 1) == 1 and not block.get("is_header") and not block.get("is_footer")
    ]
    candidate_blocks: list[dict[str, Any]] = []
    started = False
    for block in blocks[:12]:
        text = block.get("text") or ""
        first = text.splitlines()[0].strip() if text.splitlines() else ""
        if _is_end_heading(first):
            break
        if _looks_like_metadata(text) and not started:
            continue
        if len(text.strip()) >= 120:
            started = True
        if started:
            candidate_blocks.append(block)
        if sum(len(item.get("text") or "") for item in candidate_blocks) > 3500:
            break
    abstract_text = _clean_abstract_text("\n\n".join(block.get("text", "") for block in candidate_blocks))
    if len(abstract_text) < 120 or len(abstract_text) > 3800:
        return {
            "has_abstract": False,
            "abstract_text": "",
            "page_start": None,
            "page_end": None,
            "block_ids": [],
            "section_id": "",
            "boundary_source": "fallback",
            "confidence": 0.0,
            "warnings": ["No reliable abstract boundary found."],
        }
    return {
        "has_abstract": True,
        "abstract_text": abstract_text,
        "page_start": 1,
        "page_end": 1,
        "block_ids": [block.get("block_id") for block in candidate_blocks if block.get("block_id")],
        "section_id": "",
        "boundary_source": "first_page_rule",
        "confidence": 0.55,
        "warnings": [],
    }


def _mark_document(document: dict[str, Any], result: dict[str, Any]) -> None:
    document["abstract_detection"] = result
    if not result.get("has_abstract"):
        return
    section_id = result.get("section_id") or ""
    if not section_id:
        section_id = f"{document.get('paper_id')}_sec_abstract"
        document.setdefault("sections", []).insert(
            0,
            {
                "section_id": section_id,
                "paper_id": document.get("paper_id"),
                "title": "Abstract",
                "normalized_name": "abstract",
                "level": 1,
                "parent_section_id": None,
                "section_path": "Abstract",
                "page_start": result.get("page_start") or 1,
                "page_end": result.get("page_end") or result.get("page_start") or 1,
                "block_ids": result.get("block_ids") or [],
                "table_ids": [],
                "figure_ids": [],
                "summary": result.get("abstract_text") or "",
            },
        )
        result["section_id"] = section_id
    for section in document.get("sections") or []:
        if section.get("section_id") == section_id or _is_abstract_heading(_clean_heading(section.get("title") or "")):
            section["is_abstract"] = True
            section["section_role"] = "abstract"
            section["detection_confidence"] = result.get("confidence") or 0.0
            section["boundary_source"] = result.get("boundary_source") or "fallback"
        else:
            role = _section_role(section.get("normalized_name") or section.get("title") or "")
            section.setdefault("is_abstract", False)
            section.setdefault("section_role", role)
            section.setdefault("detection_confidence", 0.0)
            section.setdefault("boundary_source", "")
    abstract_blocks = set(result.get("block_ids") or [])
    for block in document.get("text_blocks") or []:
        if block.get("block_id") in abstract_blocks:
            block["is_abstract"] = True
            block["section_id"] = section_id


def _clean_heading(value: str) -> str:
    clean = re.sub(r"^\s*\d+(\.\d+)*\.?\s*", "", value.strip().lower())
    clean = re.sub(r"[:：\s]+$", "", clean)
    return clean


def _is_abstract_heading(value: str) -> bool:
    clean = _clean_heading(value)
    return clean in ABSTRACT_HEADINGS and clean not in ABSTRACT_EXCLUDE_HEADINGS


def _is_end_heading(value: str) -> bool:
    return bool(ABSTRACT_END_RE.search(value.strip()))


def _looks_like_metadata(text: str) -> bool:
    clean = text.strip()
    lowered = clean.lower()
    if len(clean) < 80:
        return True
    return any(token in lowered for token in ["doi:", "arxiv", "copyright", "@", "conference", "journal"])


def _clean_abstract_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and _is_abstract_heading(lines[0]):
        lines = lines[1:]
    kept = []
    for line in lines:
        if _is_end_heading(line):
            break
        kept.append(line)
    clean = re.sub(r"\s+", " ", " ".join(kept)).strip()
    inline_end = ABSTRACT_INLINE_END_RE.search(clean)
    if inline_end:
        clean = clean[: inline_end.start()].strip()
    return clean[:3500]


def _section_role(value: str) -> str:
    lowered = value.lower()
    mapping = {
        "introduction": ["introduction", "引言", "绪论"],
        "method": ["method", "approach", "model", "framework", "方法", "模型"],
        "experiment": ["experiment", "evaluation", "实验", "评测"],
        "result": ["result", "结果"],
        "conclusion": ["conclusion", "结论"],
        "references": ["reference", "参考文献"],
    }
    for role, tokens in mapping.items():
        if any(token in lowered or token in value for token in tokens):
            return role
    return "unknown"
