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


def test_note_skill_binds_key_sections_to_evidence_ids() -> None:
    bundle = {
        "text_chunks": [
            {"chunk_id": "method_1", "section_name": "Method", "section_role": "method", "text": "The method uses a retrieval policy.", "source_type": "text"},
            {"chunk_id": "exp_1", "section_name": "Experiments", "section_role": "experiment", "text": "The experiment uses two datasets.", "source_type": "text"},
            {"chunk_id": "result_1", "section_name": "Results", "section_role": "result", "text": "The result improves recall.", "source_type": "text"},
        ],
        "tables": [],
        "figures": [],
        "pages": [],
    }
    result = run_deep_paper_note_skill(
        paper_metadata={"id": "paper_bind", "title": "Binding Paper", "authors": "Team"},
        evidence_bundle=bundle,
        paper_text="",
        retrieved_chunks=[],
    )
    markdown = result["note_markdown"]
    assert "[method_1]" in markdown
    assert "[exp_1]" in markdown
    assert "[result_1]" in markdown
    assert "当前解析结果中没有足够证据" in markdown
    assert result["quality_check"]["has_evidence_binding"] is False
    assert "limitations" in result["quality_check"]["missing_evidence_sections"]


def test_note_skill_full_evidence_binding_marks_quality_true() -> None:
    bundle = {
        "text_chunks": [
            {"chunk_id": "method_1", "section_name": "Method", "section_role": "method", "text": "The method uses a retrieval policy.", "source_type": "text"},
            {"chunk_id": "exp_1", "section_name": "Experiments", "section_role": "experiment", "text": "The experiment uses two datasets.", "source_type": "text"},
            {"chunk_id": "result_1", "section_name": "Results", "section_role": "result", "text": "The result improves recall.", "source_type": "text"},
            {"chunk_id": "disc_1", "section_name": "Discussion", "section_role": "discussion", "text": "The discussion describes the innovation and implications.", "source_type": "text"},
            {"chunk_id": "limit_1", "section_name": "Limitations", "section_role": "limitation", "text": "The limitations mention parser noise and missing evidence.", "source_type": "text"},
        ],
        "tables": [],
        "figures": [],
        "pages": [],
    }
    result = run_deep_paper_note_skill(
        paper_metadata={"id": "paper_bind_full", "title": "Full Binding Paper", "authors": "Team"},
        evidence_bundle=bundle,
        paper_text="",
        retrieved_chunks=[],
    )
    markdown = result["note_markdown"]
    assert result["quality_check"]["has_evidence_binding"] is True
    assert result["quality_check"]["missing_evidence_sections"] == []
    expected_by_heading = [
        ("## 5.", ["[method_1]"]),
        ("## 7.", ["[exp_1]"]),
        ("## 8.", ["[result_1]"]),
        ("## 9.", ["[method_1]", "[result_1]", "[disc_1]"]),
        ("## 10.", ["[limit_1]", "[disc_1]"]),
    ]
    for heading_prefix, expected_ids in expected_by_heading:
        block = section_after(markdown, heading_prefix)
        assert any(expected in block for expected in expected_ids) or "当前解析结果中没有足够证据" in block


def section_after(markdown: str, heading_prefix: str) -> str:
    lines = markdown.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(heading_prefix))
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])
