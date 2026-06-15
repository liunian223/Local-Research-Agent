from __future__ import annotations

from note_skill import normalize_note_evidence_bundle, run_deep_paper_note_skill


def test_note_skill_prefers_structured_evidence_bundle() -> None:
    bundle = {
        "text_chunks": [
            {
                "section_name": "2 Method",
                "section_role": "method",
                "text": "The method evidence comes from body text.",
                "source_type": "text",
            }
        ],
        "abstract_chunks": [
            {
                "section_name": "Abstract",
                "is_abstract": True,
                "chunk_role": "abstract",
                "text": "The abstract is only a high-level clue.",
                "source_type": "text",
            }
        ],
        "tables": [],
        "figures": [],
        "pages": [],
    }
    result = run_deep_paper_note_skill(
        paper_metadata={"id": "paper_x", "title": "Bundle Paper", "authors": "Team"},
        evidence_bundle=bundle,
        paper_text="",
        retrieved_chunks=[],
        options={"template_version": "obsidian_note_v2"},
    )
    assert result["status"] in {"success", "partial"}
    assert result["note_evidence_bundle"]["method"]
    assert result["note_evidence_bundle"]["abstract"]
    assert result["quality_check"]["template_version"] == "obsidian_note_v2"


def test_normalize_note_evidence_bundle_falls_back_to_flat_chunks() -> None:
    normalized = normalize_note_evidence_bundle(
        {},
        [
            {
                "section_name": "3 Experiments",
                "text": "The experiment uses two datasets.",
                "source_type": "text",
            }
        ],
    )
    assert normalized["experiment"]
    assert normalized["evidence_blocks"]
