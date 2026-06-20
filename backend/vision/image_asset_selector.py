from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import config
from database import rows_to_dicts
from vision.pdf_page_renderer import render_pdf_pages


VISION_KEYWORDS = [
    "图",
    "图片",
    "图像",
    "figure",
    "fig.",
    "表",
    "table",
    "公式",
    "equation",
    "流程图",
    "架构图",
    "第几页",
    "page",
    "diagram",
]


def question_requires_vision(message: str) -> bool:
    lowered = message.lower()
    return any(keyword.lower() in lowered for keyword in VISION_KEYWORDS)


def select_image_assets(
    conn: Any,
    *,
    paper_id: str,
    question: str,
    evidence: list[dict[str, Any]],
    pdf_path: str,
) -> dict[str, Any]:
    all_assets = rows_to_dicts(
        conn.execute(
            "SELECT * FROM image_assets WHERE paper_id = ? ORDER BY page_no ASC, source_type ASC, image_index ASC, created_at ASC",
            (paper_id,),
        ).fetchall()
    )
    target_pages = _target_pages(question, evidence)
    selected = _select_from_assets(all_assets, target_pages)
    rendered_assets: list[dict[str, Any]] = []
    render_status = "not_needed"
    render_errors: list[str] = []
    if len(selected) < config.MAX_VISION_IMAGES_PER_CALL and pdf_path:
        pages_to_render = target_pages or _pages_from_evidence(evidence) or [1]
        render_result = render_pdf_pages(pdf_path, paper_id, pages_to_render)
        render_status = render_result.get("status", "unknown")
        render_errors = render_result.get("errors", [])
        rendered_assets = render_result.get("assets", [])
        for asset in rendered_assets:
            if len(selected) >= config.MAX_VISION_IMAGES_PER_CALL:
                break
            selected.append(asset)
    selected = selected[: config.MAX_VISION_IMAGES_PER_CALL]
    return {
        "selected_assets": selected,
        "selected_image_paths": [str(Path(asset["image_path"]).resolve()) for asset in selected],
        "rendered_assets": rendered_assets,
        "rendered_image_paths": [str(Path(asset["image_path"]).resolve()) for asset in rendered_assets],
        "target_pages": target_pages,
        "render_status": render_status,
        "render_errors": render_errors,
        "available_asset_count": len(all_assets),
    }


def _select_from_assets(assets: list[dict[str, Any]], target_pages: list[int]) -> list[dict[str, Any]]:
    if target_pages:
        by_page = [asset for asset in assets if int(asset.get("page_no") or 0) in target_pages]
        if by_page:
            return by_page[: config.MAX_VISION_IMAGES_PER_CALL]
    embedded = [asset for asset in assets if asset.get("source_type") == "embedded_image"]
    return (embedded or assets)[: config.MAX_VISION_IMAGES_PER_CALL]


def _target_pages(question: str, evidence: list[dict[str, Any]]) -> list[int]:
    explicit = _pages_from_text(question)
    if explicit:
        return explicit
    return _pages_from_evidence(evidence)


def _pages_from_text(text: str) -> list[int]:
    pages: list[int] = []
    patterns = [
        r"第\s*(\d+)\s*页",
        r"page\s*(\d+)",
        r"p\.\s*(\d+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            pages.append(int(match.group(1)))
    return sorted(set(pages))


def _pages_from_evidence(evidence: list[dict[str, Any]]) -> list[int]:
    pages: list[int] = []
    for item in evidence:
        for key in ["page_start", "page_no", "page_number"]:
            value = item.get(key)
            if isinstance(value, int) and value > 0:
                pages.append(value)
        metadata = item.get("metadata") or {}
        if isinstance(metadata, dict):
            for key in ["page_start", "page_no", "page_number"]:
                value = metadata.get(key)
                if isinstance(value, int) and value > 0:
                    pages.append(value)
    return sorted(set(pages))[: config.MAX_VISION_IMAGES_PER_CALL]
