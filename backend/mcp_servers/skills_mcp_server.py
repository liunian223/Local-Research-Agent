from __future__ import annotations

from typing import Any

from note_skill import run_deep_paper_note_skill as _run_deep_paper_note_skill


def run_deep_paper_note_skill(
    paper_metadata: dict[str, Any],
    evidence_bundle: dict[str, Any] | None = None,
    paper_text: str = "",
    retrieved_chunks: list[dict[str, Any]] | None = None,
    target_language: str = "zh",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _run_deep_paper_note_skill(
        paper_metadata=paper_metadata,
        evidence_bundle=evidence_bundle or {},
        paper_text=paper_text,
        retrieved_chunks=retrieved_chunks or [],
        target_language=target_language,
        options=options or {},
    )
