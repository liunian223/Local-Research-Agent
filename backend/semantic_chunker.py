from __future__ import annotations

import json
import re
from typing import Any

import config
from database import new_id, now_iso


def build_semantic_chunks(document: dict[str, Any], paper: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    blocks = {
        block["block_id"]: block
        for block in document.get("text_blocks", [])
        if not block.get("is_header") and not block.get("is_footer") and block.get("block_type") not in {"header", "footer"}
    }
    for section in document.get("sections", []):
        section_blocks = [blocks[block_id] for block_id in section.get("block_ids", []) if block_id in blocks]
        is_abstract_section = bool(section.get("is_abstract")) or section.get("section_role") == "abstract" or section.get("normalized_name") == "abstract"
        if is_abstract_section:
            abstract_blocks = [block for block in section_blocks if block.get("is_abstract") or block.get("section_id") == section.get("section_id")]
            abstract_text = _clean_abstract_boundary(document.get("abstract_detection", {}).get("abstract_text") or "\n\n".join(
                block.get("text", "")
                for block in abstract_blocks
                if block.get("block_type") not in {"caption", "header", "footer"}
            ))
            for part_index, part in enumerate(_split_abstract_text(abstract_text, paper.get("language") or ""), start=1):
                chunk = _base_chunk(
                    paper,
                    source_type="text",
                    section=section,
                    content=part,
                    block_ids=[block["block_id"] for block in abstract_blocks],
                    table_ids=[],
                    figure_ids=[],
                    chunk_index=len(chunks),
                    is_abstract=True,
                    chunk_role="abstract",
                )
                chunk["summary"] = _summarize(part)
                if part_index > 1:
                    chunk["section_title"] = f"{chunk['section_title']} ({part_index})"
                chunks.append(chunk)
            summary_content = abstract_text[: config.MAX_EVIDENCE_CHARS]
            if summary_content:
                chunks.append(
                    {
                        **_base_chunk(
                            paper,
                            source_type="section_summary",
                            section=section,
                            content=_summarize(summary_content, 900),
                            block_ids=[block["block_id"] for block in abstract_blocks],
                            table_ids=[],
                            figure_ids=[],
                            chunk_index=len(chunks),
                            is_abstract=True,
                            chunk_role="abstract",
                        ),
                        "summary": _summarize(summary_content, 300),
                    }
                )
            continue

        text_parts = [
            block.get("text", "")
            for block in section_blocks
            if block.get("block_type") not in {"caption", "header", "footer"} and not block.get("is_abstract")
        ]
        content = "\n\n".join(part.strip() for part in text_parts if part.strip())
        for part_index, part in enumerate(_split_semantic_text(content), start=1):
            chunk = _base_chunk(
                paper,
                source_type="text",
                section=section,
                content=part,
                block_ids=[block["block_id"] for block in section_blocks],
                    table_ids=section.get("table_ids", []),
                    figure_ids=section.get("figure_ids", []),
                    chunk_index=len(chunks),
                    is_abstract=False,
                    chunk_role="body",
                )
            chunk["summary"] = _summarize(part)
            if len(_split_semantic_text(content)) > 1:
                chunk["section_title"] = f"{chunk['section_title']} ({part_index})"
            chunks.append(chunk)
        summary_content = section.get("summary") or content[: config.MAX_EVIDENCE_CHARS]
        if summary_content:
            chunks.append(
                {
                    **_base_chunk(
                        paper,
                        source_type="section_summary",
                        section=section,
                        content=_summarize(summary_content, 900),
                        block_ids=[block["block_id"] for block in section_blocks],
                        table_ids=section.get("table_ids", []),
                        figure_ids=section.get("figure_ids", []),
                        chunk_index=len(chunks),
                        is_abstract=False,
                        chunk_role="section_summary",
                    ),
                    "summary": _summarize(summary_content, 300),
                }
            )

    for table in document.get("tables", []):
        section = _section_for_source(document, table)
        content = "\n\n".join(
            part
            for part in [
                table.get("caption", ""),
                table.get("summary", ""),
                table.get("structured_text", ""),
                table.get("nearby_text", ""),
            ]
            if part
        )
        chunks.append(
            {
                **_base_chunk(
                    paper,
                    source_type="table",
                    section=section,
                    content=content,
                    block_ids=[],
                    table_ids=[table.get("table_id")],
                    figure_ids=[],
                    chunk_index=len(chunks),
                    page_start=table.get("page_number"),
                    page_end=table.get("page_number"),
                    is_abstract=False,
                    chunk_role="table",
                ),
                "summary": table.get("summary") or _summarize(content),
                "metadata": {"table": table},
            }
        )

    for figure in document.get("figures", []):
        section = _section_for_source(document, figure)
        content = "\n\n".join(
            part
            for part in [
                figure.get("caption", ""),
                figure.get("visual_summary", ""),
                figure.get("nearby_text", ""),
                f"figure_image_path: {figure.get('image_path')}" if figure.get("image_path") else "",
                f"page_image_path: {figure.get('page_image_path')}" if figure.get("page_image_path") else "",
            ]
            if part
        )
        chunks.append(
            {
                **_base_chunk(
                    paper,
                    source_type="figure",
                    section=section,
                    content=content,
                    block_ids=[],
                    table_ids=[],
                    figure_ids=[figure.get("figure_id")],
                    chunk_index=len(chunks),
                    page_start=figure.get("page_number"),
                    page_end=figure.get("page_number"),
                    is_abstract=False,
                    chunk_role="figure",
                ),
                "summary": figure.get("visual_summary") or _summarize(content),
                "metadata": {"figure": figure},
            }
        )

    for index, chunk in enumerate(chunks):
        chunk["prev_chunk_id"] = chunks[index - 1]["id"] if index else ""
        chunk["next_chunk_id"] = chunks[index + 1]["id"] if index + 1 < len(chunks) else ""
        chunk["metadata"] = {
            **chunk.get("metadata", {}),
            "block_ids": chunk.get("block_ids", []),
            "table_ids": chunk.get("table_ids", []),
            "figure_ids": chunk.get("figure_ids", []),
            "context_prefix": chunk.get("context_prefix", ""),
            "parser_version": config.LAYOUT_RAG_PARSER_VERSION,
            "indexed_at": chunk.get("indexed_at", ""),
            "source_type": chunk.get("source_type", ""),
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "section_path": chunk.get("section_path", ""),
            "is_abstract": bool(chunk.get("is_abstract")),
            "chunk_role": chunk.get("chunk_role", ""),
            "section_role": chunk.get("section_role", ""),
            "retrieval_weight": chunk.get("retrieval_weight", 1.0),
        }
    document["chunks"] = chunks
    return chunks


def chunk_to_db_row(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": chunk["id"],
        "paper_id": chunk["paper_id"],
        "section_name": chunk.get("section_title") or chunk.get("section_path") or "Body",
        "chunk_index": chunk.get("chunk_index") or 0,
        "text": chunk.get("text") or chunk.get("content") or "",
        "vector_id": chunk.get("vector_id") or chunk["id"],
        "source_type": chunk.get("source_type") or "text",
        "section_id": chunk.get("section_id") or "",
        "section_path": chunk.get("section_path") or "",
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "context_prefix": chunk.get("context_prefix") or "",
        "metadata_json": json.dumps(chunk.get("metadata") or {}, ensure_ascii=False),
        "is_abstract": 1 if chunk.get("is_abstract") else 0,
        "retrieval_weight": chunk.get("retrieval_weight", 1.0),
        "chunk_role": chunk.get("chunk_role") or "",
        "section_role": chunk.get("section_role") or "",
        "created_at": chunk.get("created_at") or now_iso(),
    }


def chunk_to_document_row(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": chunk["id"],
        "paper_id": chunk["paper_id"],
        "source_type": chunk.get("source_type") or "text",
        "title": chunk.get("title") or "",
        "authors": chunk.get("authors") or "",
        "section_id": chunk.get("section_id") or "",
        "section_title": chunk.get("section_title") or "",
        "section_path": chunk.get("section_path") or "",
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "block_ids_json": json.dumps(chunk.get("block_ids") or [], ensure_ascii=False),
        "table_ids_json": json.dumps(chunk.get("table_ids") or [], ensure_ascii=False),
        "figure_ids_json": json.dumps(chunk.get("figure_ids") or [], ensure_ascii=False),
        "prev_chunk_id": chunk.get("prev_chunk_id") or "",
        "next_chunk_id": chunk.get("next_chunk_id") or "",
        "context_prefix": chunk.get("context_prefix") or "",
        "content": chunk.get("content") or "",
        "summary": chunk.get("summary") or "",
        "parser_version": chunk.get("parser_version") or config.LAYOUT_RAG_PARSER_VERSION,
        "indexed_at": chunk.get("indexed_at") or "",
        "metadata_json": json.dumps(chunk.get("metadata") or {}, ensure_ascii=False),
        "is_abstract": 1 if chunk.get("is_abstract") else 0,
        "retrieval_weight": chunk.get("retrieval_weight", 1.0),
        "chunk_role": chunk.get("chunk_role") or "",
        "parent_section_role": chunk.get("section_role") or "",
        "created_at": chunk.get("created_at") or now_iso(),
    }


def _base_chunk(
    paper: dict[str, Any],
    source_type: str,
    section: dict[str, Any],
    content: str,
    block_ids: list[str],
    table_ids: list[str],
    figure_ids: list[str],
    chunk_index: int,
    page_start: int | None = None,
    page_end: int | None = None,
    is_abstract: bool = False,
    chunk_role: str = "body",
) -> dict[str, Any]:
    indexed_at = now_iso()
    resolved_page_start = page_start or section.get("page_start") or 1
    resolved_page_end = page_end or section.get("page_end") or resolved_page_start
    context_prefix = (
        f"Paper: {paper.get('title') or 'Untitled Paper'}; "
        f"section: {section.get('section_path') or 'Body'}; "
        f"pages: {resolved_page_start}-{resolved_page_end}; "
        f"source_type: {source_type}; "
        f"chunk_role: {chunk_role}."
    )
    section_role = section.get("section_role") or ("abstract" if is_abstract else _role_from_section(section))
    return {
        "id": new_id("chunk"),
        "paper_id": paper["id"],
        "title": paper.get("title") or "",
        "authors": paper.get("authors") or "",
        "source_type": source_type,
        "section_id": section.get("section_id") or "",
        "section_title": section.get("title") or "Body",
        "section_path": section.get("section_path") or section.get("title") or "Body",
        "page_start": resolved_page_start,
        "page_end": resolved_page_end,
        "block_ids": [item for item in block_ids if item],
        "table_ids": [item for item in table_ids if item],
        "figure_ids": [item for item in figure_ids if item],
        "prev_chunk_id": "",
        "next_chunk_id": "",
        "context_prefix": context_prefix,
        "content": content.strip(),
        "text": f"{context_prefix}\n\n{content.strip()}",
        "summary": "",
        "parser_version": config.LAYOUT_RAG_PARSER_VERSION,
        "indexed_at": indexed_at,
        "chunk_index": chunk_index,
        "created_at": indexed_at,
        "vector_id": "",
        "is_abstract": is_abstract,
        "retrieval_weight": 0.65 if is_abstract else 1.0,
        "chunk_role": chunk_role,
        "section_role": section_role,
        "metadata": {},
    }


def _split_abstract_text(text: str, language: str) -> list[str]:
    limit = 1200 if language == "zh" else 1800
    clean = _clean_abstract_boundary(text)
    if not clean:
        return []
    if len(clean) <= limit:
        return [clean]
    return [clean[index : index + limit].strip() for index in range(0, len(clean), limit) if clean[index : index + limit].strip()]


def _clean_abstract_boundary(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    match = re.search(
        r"\b(keywords?|key words|index terms)\s*[:：]|(关键词|关键字)\s*[:：]|\b(1\s+introduction|1\.?\s*introduction|i\.?\s*introduction|introduction)\b|(?:^|\s)(引言|绪论|1\s*引言)\b",
        clean,
        re.I,
    )
    if match:
        clean = clean[: match.start()].strip()
    return clean


def _split_semantic_text(text: str) -> list[str]:
    clean = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not clean:
        return []
    units = [unit.strip() for unit in re.split(r"\n\s*\n", clean) if unit.strip()]
    if not units:
        units = [clean]
    chunks: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > config.SEMANTIC_CHUNK_MAX_CHARS:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_length_fallback(unit))
            continue
        if current and len(current) + len(unit) + 2 > config.SEMANTIC_CHUNK_MAX_CHARS:
            chunks.append(current.strip())
            current = unit
        else:
            current = f"{current}\n\n{unit}".strip() if current else unit
    if current:
        chunks.append(current.strip())
    return chunks


def _length_fallback(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", text) if part.strip()]
    if not sentences:
        sentences = [text]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > config.SEMANTIC_CHUNK_MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(sentence):
                end = min(len(sentence), start + config.SEMANTIC_CHUNK_MAX_CHARS)
                chunks.append(sentence[start:end])
                if end >= len(sentence):
                    break
                start = max(0, end - config.SEMANTIC_CHUNK_SOFT_OVERLAP)
            continue
        if current and len(current) + len(sentence) + 1 > config.SEMANTIC_CHUNK_MAX_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        chunks.append(current)
    return chunks


def _summarize(text: str, limit: int = 500) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:limit]


def _role_from_section(section: dict[str, Any]) -> str:
    value = f"{section.get('normalized_name', '')} {section.get('section_path', '')} {section.get('title', '')}".lower()
    mapping = {
        "introduction": ["introduction", "引言", "绪论"],
        "method": ["method", "approach", "model", "framework", "方法", "模型"],
        "experiment": ["experiment", "evaluation", "实验", "评测"],
        "result": ["result", "结果"],
        "conclusion": ["conclusion", "结论"],
        "references": ["reference", "参考文献"],
    }
    for role, tokens in mapping.items():
        if any(token in value for token in tokens):
            return role
    return "unknown"


def _section_for_source(document: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    section_id = source.get("section_id") or ""
    for section in document.get("sections", []):
        if section.get("section_id") == section_id:
            return section
    return {
        "section_id": section_id,
        "title": source.get("section_path") or "Body",
        "section_path": source.get("section_path") or "Body",
        "page_start": source.get("page_number") or 1,
        "page_end": source.get("page_number") or 1,
        "table_ids": [],
        "figure_ids": [],
    }
