from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import config
from adaptive_rag.abstract_detector import detect_abstract
from database import new_id, now_iso


SECTION_PATTERNS = [
    ("abstract", re.compile(r"^(abstract|摘要)\b", re.I)),
    ("introduction", re.compile(r"^(\d+\.?\s*)?(introduction|引言|绪论)\b", re.I)),
    ("background", re.compile(r"^(\d+\.?\s*)?(background|preliminaries|背景|预备知识)\b", re.I)),
    ("related_work", re.compile(r"^(\d+\.?\s*)?(related work|相关工作)\b", re.I)),
    ("method", re.compile(r"^(\d+\.?\s*)?(method|methodology|approach|model|framework|方法|模型|框架)\b", re.I)),
    ("algorithm", re.compile(r"^(\d+\.?\s*)?(algorithm|算法)\b", re.I)),
    ("experiment", re.compile(r"^(\d+\.?\s*)?(experiments?|evaluation|实验|实验设置)\b", re.I)),
    ("result", re.compile(r"^(\d+\.?\s*)?(results?|结果|结果分析)\b", re.I)),
    ("discussion", re.compile(r"^(\d+\.?\s*)?(discussion|讨论)\b", re.I)),
    ("conclusion", re.compile(r"^(\d+\.?\s*)?(conclusions?|结论)\b", re.I)),
    ("references", re.compile(r"^(references|参考文献)\b", re.I)),
    ("appendix", re.compile(r"^(appendix|附录)\b", re.I)),
]

ENGLISH_SECTION_TITLES = {
    "abstract": "abstract",
    "introduction": "introduction",
    "related work": "related_work",
    "method": "method",
    "methods": "method",
    "methodology": "method",
    "materials and methods": "method",
    "approach": "method",
    "experiment": "experiment",
    "experiments": "experiment",
    "experimental setup": "experiment",
    "evaluation": "experiment",
    "results": "result",
    "result": "result",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "references": "references",
}

SECTION_SENTENCE_MARKERS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "can",
    "for",
    "from",
    "given",
    "has",
    "have",
    "highlight",
    "highlights",
    "in",
    "into",
    "is",
    "of",
    "our",
    "show",
    "shows",
    "takes",
    "that",
    "the",
    "these",
    "this",
    "to",
    "we",
    "were",
    "with",
}

CAPTION_RE = re.compile(r"^(table|fig\.?|figure|表|图)\s*[\dIVXivx一二三四五六七八九十]+[.:：\s-]", re.I)
TABLE_RE = re.compile(r"^(table|表)\s*[\dIVXivx一二三四五六七八九十]+", re.I)
FIGURE_RE = re.compile(r"^(fig\.?|figure|图)\s*[\dIVXivx一二三四五六七八九十]+", re.I)


def parse_pdf_layout(path: Path, paper: dict[str, Any], parsed_text: str = "") -> dict[str, Any]:
    warnings: list[str] = []
    doc = None
    try:
        import fitz

        doc = fitz.open(path)
        pages, blocks = _extract_pages_and_blocks(doc, paper["id"])
    except Exception as exc:
        warnings.append(f"layout_parser_failed: {exc}")
        pages, blocks = _fallback_pages_and_blocks(parsed_text, paper["id"])

    _assign_header_footer(pages, blocks)
    sections = _detect_sections(paper["id"], blocks, pages)
    _assign_sections_to_blocks(blocks, sections)
    abstract_detection = None
    if config.RAG_ABSTRACT_DETECTION_ENABLED:
        abstract_detection = detect_abstract({"paper_id": paper["id"], "sections": sections, "text_blocks": blocks})
    tables = _extract_caption_sources(paper["id"], blocks, sections, "table")
    figures = _extract_caption_sources(paper["id"], blocks, sections, "figure")
    if doc is not None:
        try:
            _extract_visual_assets(doc, paper["id"], pages, figures)
        except Exception as exc:
            warnings.append(f"visual_asset_extraction_failed: {exc}")
        finally:
            try:
                doc.close()
            except Exception:
                pass
    _link_page_sources(pages, blocks, tables, figures)

    document = {
        "paper_id": paper["id"],
        "title": paper.get("title") or "",
        "authors": paper.get("authors") or "",
        "year": paper.get("year") or "",
        "doi": paper.get("doi") or "",
        "language": paper.get("language") or "unknown",
        "page_count": paper.get("page_count") or len(pages),
        "source_pdf_path": paper.get("file_path") or str(path),
        "source_pdf_sha256": paper.get("file_sha256") or "",
        "parser_version": config.LAYOUT_RAG_PARSER_VERSION,
        "parsed_at": now_iso(),
        "pages": pages,
        "sections": sections,
        "text_blocks": blocks,
        "tables": tables,
        "figures": figures,
        "chunks": [],
        "parse_status": paper.get("parse_status") or "partial",
        "parse_warnings": warnings,
        "abstract_detection": abstract_detection or {"has_abstract": False, "warnings": ["Abstract detection disabled."]},
    }
    return document


def save_layout_artifacts(document: dict[str, Any]) -> Path:
    root = config.PARSED_DIR / document["paper_id"]
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "tables").mkdir(parents=True, exist_ok=True)
    (root / "figures").mkdir(parents=True, exist_ok=True)
    (root / "summaries").mkdir(parents=True, exist_ok=True)
    payloads = {
        "layout.json": document,
        "metadata.json": {key: document.get(key) for key in ["paper_id", "title", "authors", "year", "doi", "language", "page_count", "source_pdf_path", "source_pdf_sha256", "parser_version", "parsed_at", "parse_status"]},
        "pages.json": document.get("pages", []),
        "sections.json": document.get("sections", []),
        "blocks.json": document.get("text_blocks", []),
    }
    for name, payload in payloads.items():
        (root / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for table in document.get("tables", []):
        (root / "tables" / f"{table['table_id']}.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    for figure in document.get("figures", []):
        (root / "figures" / f"{figure['figure_id']}.json").write_text(json.dumps(figure, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def _extract_pages_and_blocks(doc: Any, paper_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    order = 0
    for page_index, page in enumerate(doc, start=1):
        rect = page.rect
        page_blocks: list[str] = []
        page_info = {
            "page_id": f"{paper_id}_page_{page_index:03d}",
            "paper_id": paper_id,
            "page_number": page_index,
            "width": float(rect.width),
            "height": float(rect.height),
            "header_text": "",
            "footer_text": "",
            "main_text": "",
            "block_ids": page_blocks,
            "table_ids": [],
            "figure_ids": [],
        }
        raw_blocks = _extract_page_text_blocks(page)
        for raw in raw_blocks:
            text = re.sub(r"\s+\n", "\n", str(raw.get("text") or "")).strip()
            if not text:
                continue
            block_id = f"{paper_id}_block_{len(blocks) + 1:04d}"
            block = {
                "block_id": block_id,
                "paper_id": paper_id,
                "page_number": page_index,
                "block_type": "text",
                "text": text,
                "bbox": raw.get("bbox") or [0, 0, 0, 0],
                "font_size": raw.get("font_size", 0),
                "max_font_size": raw.get("max_font_size", 0),
                "avg_font_size": raw.get("avg_font_size", 0),
                "bold": bool(raw.get("bold")),
                "uppercase_ratio": raw.get("uppercase_ratio", 0),
                "section_id": "",
                "reading_order": order,
                "is_header": False,
                "is_footer": False,
            }
            block["block_type"] = _classify_block(text, block, page_info)
            blocks.append(block)
            page_blocks.append(block_id)
            order += 1
        pages.append(page_info)
    return pages, blocks


def _extract_page_text_blocks(page: Any) -> list[dict[str, Any]]:
    try:
        data = page.get_text("dict", sort=True) or {}
        blocks = []
        for raw_block in data.get("blocks") or []:
            if raw_block.get("type") not in {0, None}:
                continue
            lines = raw_block.get("lines") or []
            text_lines: list[str] = []
            sizes: list[float] = []
            fonts: list[str] = []
            for line in lines:
                spans = [span for span in line.get("spans") or [] if str(span.get("text") or "").strip()]
                if not spans:
                    continue
                text_lines.append("".join(str(span.get("text") or "") for span in spans).strip())
                for span in spans:
                    sizes.append(float(span.get("size") or 0))
                    fonts.append(str(span.get("font") or ""))
            text = "\n".join(line for line in text_lines if line).strip()
            if not text:
                continue
            letters = re.findall(r"[A-Za-z]", text)
            uppercase = sum(1 for letter in letters if letter.isupper())
            blocks.append(
                {
                    "text": text,
                    "bbox": [float(value) for value in raw_block.get("bbox", [0, 0, 0, 0])],
                    "font_size": max(sizes) if sizes else 0,
                    "max_font_size": max(sizes) if sizes else 0,
                    "avg_font_size": sum(sizes) / len(sizes) if sizes else 0,
                    "bold": any("bold" in font.lower() for font in fonts),
                    "uppercase_ratio": uppercase / len(letters) if letters else 0,
                }
            )
        if blocks:
            return blocks
    except Exception:
        pass
    return [
        {
            "text": str(raw[4] or ""),
            "bbox": [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])],
            "font_size": 0,
            "max_font_size": 0,
            "avg_font_size": 0,
            "bold": False,
            "uppercase_ratio": 0,
        }
        for raw in (page.get_text("blocks", sort=True) or [])
        if len(raw) >= 5
    ]


def _fallback_pages_and_blocks(text: str, paper_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    block = {
        "block_id": f"{paper_id}_block_0001",
        "paper_id": paper_id,
        "page_number": 1,
        "block_type": "title" if _is_section_heading(text.splitlines()[0] if text else "") else "text",
        "text": text,
        "bbox": [0, 0, 0, 0],
        "font_size": 0,
        "max_font_size": 0,
        "avg_font_size": 0,
        "bold": False,
        "uppercase_ratio": 0,
        "section_id": "",
        "reading_order": 0,
        "is_header": False,
        "is_footer": False,
    }
    page = {
        "page_id": f"{paper_id}_page_001",
        "paper_id": paper_id,
        "page_number": 1,
        "width": 0,
        "height": 0,
        "header_text": "",
        "footer_text": "",
        "main_text": text,
        "block_ids": [block["block_id"]] if text else [],
        "table_ids": [],
        "figure_ids": [],
    }
    return [page], [block] if text else []


def _classify_block(text: str, block: dict[str, Any] | None = None, page: dict[str, Any] | None = None) -> str:
    first = text.splitlines()[0].strip()
    if any(CAPTION_RE.search(line.strip()) for line in text.splitlines()):
        return "caption"
    if _is_section_heading(first, block, page):
        return "title"
    if re.match(r"^[-*•]\s+", first):
        return "list"
    return "text"


def _assign_header_footer(pages: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> None:
    by_page = {page["page_number"]: page for page in pages}
    for block in blocks:
        page = by_page.get(block["page_number"])
        bbox = block.get("bbox") or [0, 0, 0, 0]
        height = page.get("height") or 0 if page else 0
        text = block.get("text") or ""
        looks_like_margin_noise = len(text) < 120 and len(text.splitlines()) <= 2
        if height and looks_like_margin_noise and bbox[1] < height * 0.06:
            block["is_header"] = True
            block["block_type"] = "header"
        elif height and looks_like_margin_noise and bbox[3] > height * 0.94:
            block["is_footer"] = True
            block["block_type"] = "footer"
        if page:
            if block["is_header"]:
                page["header_text"] = _join_text(page.get("header_text", ""), text)
            elif block["is_footer"]:
                page["footer_text"] = _join_text(page.get("footer_text", ""), text)
            else:
                page["main_text"] = _join_text(page.get("main_text", ""), text)


def _detect_sections(paper_id: str, blocks: list[dict[str, Any]], pages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    page_by_number = {page.get("page_number"): page for page in pages or []}
    for block in blocks:
        if block.get("is_header") or block.get("is_footer"):
            continue
        first = (block.get("text") or "").splitlines()[0].strip()
        if not _is_section_heading(first, block, page_by_number.get(block.get("page_number"))):
            continue
        normalized = normalize_section_name(first)
        section_id = f"{paper_id}_sec_{len(sections) + 1:03d}"
        sections.append(
            {
                "section_id": section_id,
                "paper_id": paper_id,
                "title": first[:240],
                "normalized_name": normalized,
                "level": _heading_level(first),
                "parent_section_id": None,
                "section_path": first[:240],
                "page_start": block["page_number"],
                "page_end": block["page_number"],
                "block_ids": [block["block_id"]],
                "table_ids": [],
                "figure_ids": [],
                "summary": "",
            }
        )
    if not sections:
        max_page = max((block.get("page_number") or 1 for block in blocks), default=1)
        sections.append(
            {
                "section_id": f"{paper_id}_sec_001",
                "paper_id": paper_id,
                "title": "Body",
                "normalized_name": "unknown",
                "level": 1,
                "parent_section_id": None,
                "section_path": "Body",
                "page_start": 1,
                "page_end": max_page,
                "block_ids": [],
                "table_ids": [],
                "figure_ids": [],
                "summary": "",
            }
        )
    return sections


def _assign_sections_to_blocks(blocks: list[dict[str, Any]], sections: list[dict[str, Any]]) -> None:
    current = sections[0]
    section_by_id = {section["section_id"]: section for section in sections}
    title_to_id = {(section["title"], section["page_start"]): section["section_id"] for section in sections}
    for block in blocks:
        key = (((block.get("text") or "").splitlines()[0].strip())[:240], block.get("page_number"))
        if key in title_to_id:
            current = section_by_id[title_to_id[key]]
        block["section_id"] = current["section_id"]
        if not block.get("is_header") and not block.get("is_footer"):
            current.setdefault("block_ids", [])
            if block["block_id"] not in current["block_ids"]:
                current["block_ids"].append(block["block_id"])
            current["page_end"] = max(current.get("page_end") or block["page_number"], block["page_number"])
    for section in sections:
        texts = [block.get("text", "") for block in blocks if block.get("section_id") == section["section_id"] and not block.get("is_header") and not block.get("is_footer")]
        section["summary"] = re.sub(r"\s+", " ", " ".join(texts))[:500]


def _extract_caption_sources(paper_id: str, blocks: list[dict[str, Any]], sections: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    section_map = {section["section_id"]: section for section in sections}
    sources: list[dict[str, Any]] = []
    matcher = TABLE_RE if kind == "table" else FIGURE_RE
    for block in blocks:
        lines = [line.strip() for line in (block.get("text") or "").splitlines() if line.strip()]
        for line_index, line in enumerate(lines):
            if not matcher.search(line):
                continue
            section = section_map.get(block.get("section_id") or "")
            nearby = _caption_nearby_text(lines, line_index) or _nearby_text(blocks, block)
            source_id = f"{paper_id}_{'table' if kind == 'table' else 'fig'}_{len(sources) + 1:03d}"
            common = {
                "paper_id": paper_id,
                "page_number": block.get("page_number") or 1,
                "section_id": block.get("section_id") or "",
                "section_path": section.get("section_path", "Body") if section else "Body",
                "caption": line,
                "bbox": block.get("bbox") or [0, 0, 0, 0],
                "nearby_text": nearby,
                "extraction_status": "partial",
                "warnings": ["caption_based_extraction"],
            }
            if kind == "table":
                structured = _table_structured_text("\n".join(lines[line_index:]))
                item = {
                    **common,
                    "table_id": source_id,
                    "columns": _guess_table_columns(structured),
                    "row_count": max(0, len(structured.splitlines()) - 2) if structured else 0,
                    "structured_text": structured,
                    "summary": _rule_summary("table", common, structured),
                }
                if section:
                    section.setdefault("table_ids", []).append(source_id)
            else:
                item = {
                    **common,
                    "figure_id": source_id,
                    "image_path": "",
                    "page_image_path": "",
                    "visual_summary": _rule_summary("figure", common, ""),
                    "summary_source": "caption_nearby_text",
                }
                if section:
                    section.setdefault("figure_ids", []).append(source_id)
            sources.append(item)
    return sources


def _extract_visual_assets(doc: Any, paper_id: str, pages: list[dict[str, Any]], figures: list[dict[str, Any]]) -> None:
    root = config.PARSED_DIR / paper_id
    page_dir = root / "pages"
    figure_dir = root / "figures"
    page_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    page_image_by_number: dict[int, str] = {}
    for page_info in pages:
        page_number = int(page_info.get("page_number") or 0)
        if not page_number or page_number > len(doc):
            continue
        image_path = page_dir / f"page_{page_number:03d}.png"
        page = doc[page_number - 1]
        pix = page.get_pixmap(matrix=_fitz_matrix(1.2), alpha=False)
        pix.save(str(image_path))
        rel_path = _relative_to_root(image_path)
        page_info["image_path"] = rel_path
        page_image_by_number[page_number] = rel_path
    for figure in figures:
        page_number = int(figure.get("page_number") or 0)
        if not page_number or page_number > len(doc):
            continue
        figure["page_image_path"] = page_image_by_number.get(page_number, "")
        image_path = figure_dir / f"{figure['figure_id']}.png"
        page = doc[page_number - 1]
        clip = _figure_clip_rect(page, figure.get("bbox") or [])
        pix = page.get_pixmap(matrix=_fitz_matrix(1.6), clip=clip, alpha=False)
        pix.save(str(image_path))
        figure["image_path"] = _relative_to_root(image_path)
        figure["extraction_status"] = "image_extracted"
        warnings = list(figure.get("warnings") or [])
        if "caption_based_extraction" not in warnings:
            warnings.append("caption_based_extraction")
        figure["warnings"] = warnings


def _fitz_matrix(scale: float) -> Any:
    import fitz

    return fitz.Matrix(scale, scale)


def _figure_clip_rect(page: Any, bbox: list[float]) -> Any:
    import fitz

    page_rect = page.rect
    if len(bbox) != 4:
        return page_rect
    x0, y0, x1, y1 = [float(value) for value in bbox]
    width = page_rect.width
    height = page_rect.height
    clip = fitz.Rect(
        max(0, x0 - width * 0.08),
        max(0, y0 - height * 0.45),
        min(width, x1 + width * 0.08),
        min(height, y1 + height * 0.08),
    )
    if clip.is_empty or clip.width < 20 or clip.height < 20:
        return page_rect
    return clip


def _relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.ROOT_DIR.resolve()))
    except Exception:
        return str(path)


def _link_page_sources(pages: list[dict[str, Any]], blocks: list[dict[str, Any]], tables: list[dict[str, Any]], figures: list[dict[str, Any]]) -> None:
    for page in pages:
        page_num = page["page_number"]
        page["table_ids"] = [item["table_id"] for item in tables if item.get("page_number") == page_num]
        page["figure_ids"] = [item["figure_id"] for item in figures if item.get("page_number") == page_num]
        if not page.get("main_text"):
            texts = [block["text"] for block in blocks if block.get("page_number") == page_num and not block.get("is_header") and not block.get("is_footer")]
            page["main_text"] = "\n\n".join(texts)


def _nearby_text(blocks: list[dict[str, Any]], block: dict[str, Any], window: int = 2) -> str:
    same_page = [item for item in blocks if item.get("page_number") == block.get("page_number") and not item.get("is_header") and not item.get("is_footer")]
    index = next((idx for idx, item in enumerate(same_page) if item["block_id"] == block["block_id"]), -1)
    if index < 0:
        return ""
    selected = same_page[max(0, index - window) : index] + same_page[index + 1 : index + 1 + window]
    return re.sub(r"\s+", " ", " ".join(item.get("text", "") for item in selected))[:1200]


def _caption_nearby_text(lines: list[str], line_index: int, window: int = 3) -> str:
    selected = lines[max(0, line_index - window) : line_index] + lines[line_index + 1 : line_index + 1 + window]
    return re.sub(r"\s+", " ", " ".join(selected))[:1200]


def _table_structured_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return text
    rows = [re.split(r"\s{2,}|\t", line) for line in lines]
    if not rows or len(rows[0]) < 2:
        return text
    header = rows[0]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows[1:20]:
        padded = row + [""] * max(0, len(header) - len(row))
        out.append("| " + " | ".join(padded[: len(header)]) + " |")
    return "\n".join(out)


def _guess_table_columns(structured: str) -> list[str]:
    first = next((line for line in structured.splitlines() if line.startswith("|")), "")
    if not first:
        return []
    return [part.strip() for part in first.strip("|").split("|") if part.strip()]


def _rule_summary(kind: str, common: dict[str, Any], structured: str) -> str:
    label = "table" if kind == "table" else "figure"
    parts = [
        f"This {label} is on page {common.get('page_number')}",
        f"section {common.get('section_path') or 'Body'}",
    ]
    if common.get("caption"):
        parts.append(f"caption: {common['caption']}")
    if structured:
        parts.append(f"content preview: {structured[:300]}")
    elif common.get("nearby_text"):
        parts.append(f"nearby text: {common['nearby_text'][:300]}")
    return ". ".join(parts)


def _is_section_heading(text: str, block: dict[str, Any] | None = None, page: dict[str, Any] | None = None) -> bool:
    clean = _clean_heading_candidate(text)
    if not clean or len(clean) > 120:
        return False
    if _looks_like_body_sentence(clean):
        return False

    normalized = _normalized_heading_text(clean)
    if normalized in ENGLISH_SECTION_TITLES:
        return True
    if any(pattern.fullmatch(clean) for _, pattern in SECTION_PATTERNS):
        return True

    numbered = re.match(r"^(?:\d+(?:\.\d+)*|[IVX]{1,6})\.?\s+(.+)$", clean, re.I)
    if numbered:
        title = _normalized_heading_text(numbered.group(1))
        if title in ENGLISH_SECTION_TITLES:
            return True
        return _is_short_title_like(numbered.group(1), block, page)

    if _is_short_title_like(clean, block, page):
        return True
    return False


def _clean_heading_candidate(text: str) -> str:
    first = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    return re.sub(r"\s+", " ", first).strip()


def _normalized_heading_text(text: str) -> str:
    clean = _clean_heading_candidate(text)
    clean = re.sub(r"^(?:\d+(?:\.\d+)*|[IVX]{1,6})\.?\s+", "", clean, flags=re.I)
    clean = clean.strip(" .:-\u2013\u2014").lower()
    clean = re.sub(r"\s+", " ", clean)
    return clean


def _looks_like_body_sentence(text: str) -> bool:
    clean = text.strip()
    lowered = clean.lower()
    if re.match(r"^abstract\s*[-\u2013\u2014:]\s+\w+", clean, re.I):
        return True
    if clean[0].islower():
        return True
    if clean.endswith("-") and len(clean.split()) >= 5:
        return True
    if re.search(r"[.!?]\s+[A-Z]", clean):
        return True
    words = re.findall(r"[A-Za-z]+", clean)
    if len(words) > 10:
        return True
    if len(words) >= 6 and sum(1 for word in words if word.lower() in SECTION_SENTENCE_MARKERS) >= 2:
        return True
    if lowered.startswith(("model ", "these ", "this ", "we ", "our ", "the ")):
        return True
    return False


def _is_short_title_like(text: str, block: dict[str, Any] | None = None, page: dict[str, Any] | None = None) -> bool:
    clean = _clean_heading_candidate(text)
    words = re.findall(r"[A-Za-z0-9]+", clean)
    if not 1 <= len(words) <= 8 or clean.endswith("."):
        return False
    if any(word.lower() in SECTION_SENTENCE_MARKERS for word in words) and len(words) > 4:
        return False
    letters = re.findall(r"[A-Za-z]", clean)
    uppercase_ratio = (sum(1 for letter in letters if letter.isupper()) / len(letters)) if letters else 0
    style_score = 0
    if block:
        style_score += 1 if block.get("bold") else 0
        style_score += 1 if float(block.get("max_font_size") or 0) >= 11.5 else 0
        style_score += 1 if float(block.get("uppercase_ratio") or uppercase_ratio) >= 0.55 else 0
        bbox = block.get("bbox") or []
        if len(bbox) == 4 and page and page.get("height"):
            y0 = float(bbox[1])
            if y0 < float(page["height"]) * 0.25:
                style_score += 1
    if uppercase_ratio >= 0.65 and len(words) <= 6:
        style_score += 1
    return style_score >= 2


def normalize_section_name(title: str) -> str:
    normalized = _normalized_heading_text(title)
    if normalized in ENGLISH_SECTION_TITLES:
        return ENGLISH_SECTION_TITLES[normalized]
    for normalized, pattern in SECTION_PATTERNS:
        if pattern.search(title.strip()):
            return normalized
    return "unknown"


def _heading_level(title: str) -> int:
    match = re.match(r"^(\d+(?:\.\d+)*)", title.strip())
    if match:
        return match.group(1).count(".") + 1
    return 1


def _join_text(existing: str, text: str) -> str:
    if not existing:
        return text.strip()
    return f"{existing}\n{text.strip()}".strip()
