from __future__ import annotations

from typing import Any

from note_skill import run_deep_paper_note_skill as _run_deep_paper_note_skill


def run_deep_paper_note_skill(
    paper_metadata: dict[str, Any],
    paper_text: str,
    retrieved_chunks: list[dict[str, Any]],
    target_language: str = "zh",
) -> dict[str, Any]:
    return _run_deep_paper_note_skill(paper_metadata, paper_text, retrieved_chunks, target_language)
