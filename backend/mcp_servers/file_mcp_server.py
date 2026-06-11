from pathlib import Path
from typing import Any

from pdf_tools import extract_text_with_fallback


def save_uploaded_pdf(path: Path, data: bytes) -> int:
    return path.write_bytes(data)


def read_pdf_text(path: Path) -> dict[str, Any]:
    return extract_text_with_fallback(path)


def write_markdown_note(path: Path, markdown: str) -> int:
    return path.write_text(markdown, encoding="utf-8")


def read_markdown_note(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def copy_pdf_to_obsidian(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    return target
