from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", stem).strip("._")
    return stem[:90] or "paper"


def guess_language(text: str) -> str:
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    if zh_chars > max(20, letters // 4):
        return "zh"
    return "en"


def extract_text_with_fallback(path: Path) -> dict[str, Any]:
    warnings: list[str] = []
    text = ""
    page_count = 0

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(path)
        page_count = doc.page_count
        pages = [page.get_text("text", sort=True) for page in doc]
        text = "\n\n".join(pages).strip()
        if len(text) >= 200:
            return {"text": text, "page_count": page_count, "parser": "pymupdf", "warnings": warnings}
        warnings.append("PyMuPDF extracted too little text.")
    except Exception as exc:
        warnings.append(f"PyMuPDF failed: {exc}")

    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            page_count = page_count or len(pdf.pages)
            pages = [(page.extract_text() or "") for page in pdf.pages]
        text = "\n\n".join(pages).strip()
        if len(text) >= 200:
            return {"text": text, "page_count": page_count, "parser": "pdfplumber", "warnings": warnings}
        warnings.append("pdfplumber extracted too little text.")
    except Exception as exc:
        warnings.append(f"pdfplumber failed: {exc}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page_count = page_count or len(reader.pages)
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n\n".join(pages).strip()
        if len(text) >= 80:
            warnings.append("Only partial text was extracted.")
            return {"text": text, "page_count": page_count, "parser": "pypdf", "warnings": warnings}
        warnings.append("pypdf extracted too little text.")
    except Exception as exc:
        warnings.append(f"pypdf failed: {exc}")

    return {"text": text, "page_count": page_count, "parser": "failed", "warnings": warnings}


def extract_metadata(path: Path, text: str, page_count: int) -> dict[str, Any]:
    title = ""
    authors = ""
    year = ""
    doi = ""
    source = "filename"
    confidence = 0.35
    warning = ""

    try:
        import fitz

        doc = fitz.open(path)
        meta = doc.metadata or {}
        title = (meta.get("title") or "").strip()
        authors = (meta.get("author") or "").strip()
        if title:
            source = "pdf_metadata"
            confidence = 0.78
    except Exception:
        warning = "PDF metadata unavailable; used text and filename fallback."

    first_lines = [line.strip() for line in text.splitlines() if line.strip()][:20]
    if not title and first_lines:
        title = first_lines[0][:240]
        source = "first_page_heuristic"
        confidence = 0.62
    if not authors and len(first_lines) > 1:
        candidate = first_lines[1]
        if 3 <= len(candidate) <= 240 and not re.search(r"abstract|摘要|introduction|引言", candidate, re.I):
            authors = candidate
    if not title:
        title = safe_filename(path.name).replace("_", " ")
        warning = warning or "No reliable title found; used filename."

    year_match = re.search(r"\b(19|20)\d{2}\b", text[:5000] + " " + path.name)
    if year_match:
        year = year_match.group(0)
    doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text[:8000], re.I)
    if doi_match:
        doi = doi_match.group(0).rstrip(".")

    return {
        "title": title,
        "authors": authors or "Unknown authors",
        "year": year,
        "language": guess_language(text + title),
        "doi": doi,
        "page_count": page_count,
        "metadata_source": source,
        "metadata_confidence": confidence,
        "metadata_warning": warning,
    }
