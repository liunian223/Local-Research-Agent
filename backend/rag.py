from __future__ import annotations

import re
from collections import Counter
from typing import Any

import config
from database import new_id, now_iso


def split_chunks(text: str, language: str = "en") -> list[dict[str, Any]]:
    size = config.CHUNK_SIZE_ZH if language == "zh" else config.CHUNK_SIZE_EN
    overlap = min(config.CHUNK_OVERLAP, max(0, size // 3))
    clean = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks: list[dict[str, Any]] = []
    start = 0
    index = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        chunk_text = clean[start:end].strip()
        if chunk_text:
            chunks.append({"id": new_id("chunk"), "chunk_index": index, "section_name": infer_section(chunk_text), "text": chunk_text})
            index += 1
        if end >= len(clean):
            break
        start = max(0, end - overlap)
    return chunks


def infer_section(text: str) -> str:
    first = text.splitlines()[0][:80] if text.splitlines() else ""
    lowered = first.lower()
    for name in ["abstract", "introduction", "method", "experiment", "result", "discussion", "conclusion"]:
        if name in lowered:
            return name.title()
    for name in ["摘要", "引言", "方法", "实验", "结果", "讨论", "结论"]:
        if name in first:
            return name
    return "Body"


def tokenize(text: str) -> list[str]:
    zh = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    en = re.findall(r"[A-Za-z0-9]{3,}", text.lower())
    return zh + en


def score_chunks(query: str, rows: list[dict[str, Any]], top_k: int | None = None) -> list[dict[str, Any]]:
    top_k = top_k or config.RAG_TOP_K
    q = Counter(tokenize(query))
    if not q:
        return []
    scored = []
    for row in rows:
        terms = Counter(tokenize(row.get("text") or ""))
        score = sum(min(count, terms.get(term, 0)) for term, count in q.items())
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    evidence = []
    for rank, (score, row) in enumerate(scored[:top_k], start=1):
        text = (row.get("text") or "")[: config.MAX_EVIDENCE_CHARS]
        evidence.append(
            {
                "rank": rank,
                "score": score,
                "source_type": row.get("source_type", "paper"),
                "paper_id": row.get("paper_id"),
                "note_id": row.get("note_id"),
                "chunk_id": row.get("id"),
                "section_name": row.get("section_name") or "Body",
                "text": text,
            }
        )
    return evidence


def note_to_chunks(note_id: str, paper_id: str, markdown: str) -> list[dict[str, Any]]:
    chunks = split_chunks(markdown, "zh")
    for chunk in chunks:
        chunk["id"] = new_id("notechunk")
        chunk["note_id"] = note_id
        chunk["paper_id"] = paper_id
        chunk["created_at"] = now_iso()
    return chunks
