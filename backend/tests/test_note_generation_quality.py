from __future__ import annotations

import harness.agent_service as agent_service
from harness.agent_service import NOTE_RETRIEVAL_PLAN, assess_note_evidence_coverage, finalize_note_generation_evidence, has_partial_note_fallback, note_logical_and_artifact_sections, retrieve_note_plan_evidence
from layout_parser import _detect_sections, _is_section_heading


def test_note_evidence_coverage_requires_key_section_body_evidence() -> None:
    evidence = [
        {"section_name": "Abstract", "is_abstract": True, "source_type": "text", "text": "Abstract evidence."},
        {"section_name": "2 Method", "source_type": "text", "text": "Method body evidence."},
        {"section_name": "3 Experiments", "source_type": "text", "text": "Experiment body evidence."},
    ]

    coverage = assess_note_evidence_coverage(evidence)

    assert coverage["ok"] is False
    assert "introduction" in coverage["missing_key_evidence"]
    assert "result" in coverage["missing_key_evidence"]
    assert coverage["missing_many_key_sections"] is True


def test_note_evidence_coverage_accepts_chapterized_body_evidence() -> None:
    evidence = [
        {"section_name": "Abstract", "is_abstract": True, "source_type": "text", "text": "Abstract evidence."},
        {"section_name": "1 Introduction", "source_type": "text", "text": "Introduction evidence."},
        {"section_name": "2 Method", "source_type": "text", "text": "Method evidence."},
        {"section_name": "3 Evaluation", "source_type": "text", "text": "Experiment evidence."},
        {"section_name": "4 Results", "source_type": "text", "text": "Result evidence."},
        {"section_name": "5 Conclusion", "source_type": "text", "text": "Conclusion evidence."},
    ]

    coverage = assess_note_evidence_coverage(evidence)

    assert coverage["ok"] is True
    assert coverage["missing_key_evidence"] == []


def test_partial_note_fallback_includes_llm_local_template_downgrade() -> None:
    assert has_partial_note_fallback(["llm_note_generation_failed_local_note_used"]) is True
    assert has_partial_note_fallback(["llm_note_generation_incomplete_local_note_used"]) is True


def test_generate_note_retrieval_plan_forces_abstract_first(monkeypatch) -> None:
    rows = [
        {"chunk_id": "abs", "section_name": "Abstract", "source_type": "text", "is_abstract": True, "text": "Abstract overview."},
        {"chunk_id": "intro", "section_name": "1 Introduction", "source_type": "text", "text": "Introduction evidence."},
        {"chunk_id": "method", "section_name": "2 Method", "source_type": "text", "text": "Method evidence."},
        {"chunk_id": "exp", "section_name": "3 Experiment", "source_type": "text", "text": "Experiment evidence."},
        {"chunk_id": "res", "section_name": "4 Results", "source_type": "text", "text": "Result evidence."},
        {"chunk_id": "con", "section_name": "5 Conclusion", "source_type": "text", "text": "Conclusion evidence."},
        {"chunk_id": "lim", "section_name": "6 Limitations", "source_type": "text", "text": "Limitation evidence."},
    ]
    queries = []

    def fake_collect(conn, scope, paper_id):
        return rows

    def fake_retrieve(gateway, conn, scope, paper_id, query):
        queries.append(query)
        return [], {"backend": "fake"}

    monkeypatch.setattr(agent_service, "collect_structured_scope_chunks", fake_collect)
    monkeypatch.setattr(agent_service, "retrieve_evidence", fake_retrieve)

    evidence, meta = retrieve_note_plan_evidence(None, None, {"id": "paper1", "title": "Paper"}, "generate note", [], {})

    assert [plan["name"] for plan in NOTE_RETRIEVAL_PLAN] == [
        "abstract",
        "background_introduction",
        "method",
        "experiment",
        "result",
        "discussion_conclusion",
        "limitation",
    ]
    assert evidence[0]["chunk_id"] == "abs"
    assert evidence[0]["note_plan_source"] == "forced_abstract"
    assert meta["force_abstract_included"] is True
    assert meta["abstract_control"]["mode"] == "force_include_no_downweight"
    assert any("background introduction" in query for query in queries)
    assert any("limitation limitations" in query for query in queries)


def test_note_final_evidence_prefers_body_text_and_limits_visuals() -> None:
    evidence = [
        {"chunk_id": "abs", "section_name": "Abstract", "source_type": "text", "is_abstract": True, "text": "Abstract overview."},
        {"chunk_id": "method", "section_name": "Method", "source_type": "text", "text": "Method body evidence."},
        {"chunk_id": "exp", "section_name": "Experimental Setup", "source_type": "text", "text": "Experiment body evidence."},
        *[
            {"chunk_id": f"fig{i}", "section_name": "Results", "source_type": "figure", "text": f"Figure {i} visual evidence."}
            for i in range(8)
        ],
    ]
    rows = [
        *evidence,
        {"chunk_id": "result_text", "section_name": "Body", "source_type": "text", "text": "The results show higher accuracy and performance compared with baselines."},
        {"chunk_id": "conclusion_text", "section_name": "Body", "source_type": "text", "text": "In conclusion, future work should address limitations."},
    ]

    final, meta = finalize_note_generation_evidence(evidence, rows)
    visual_count = sum(1 for item in final if item.get("source_type") == "figure")
    coverage = assess_note_evidence_coverage(final)

    assert final[0]["chunk_id"] == "abs"
    assert visual_count <= meta["visual_evidence_limit"]
    assert meta["fallback_added"]["result"] >= 1
    assert meta["fallback_added"]["conclusion"] >= 1
    assert coverage["body_section_counts"]["result"] >= 1
    assert coverage["body_section_counts"]["conclusion"] >= 1


def test_artifact_sections_are_separated_from_logical_retrieved_sections() -> None:
    evidence = [
        {"chunk_id": "intro", "section_name": "I. INTRODUCTION", "section_path": "I. INTRODUCTION", "source_type": "text", "text": "Introduction evidence."},
        {"chunk_id": "method", "section_name": "III. METHOD", "section_path": "III. METHOD", "source_type": "text", "text": "Method evidence."},
        {"chunk_id": "table2", "section_name": "TABLEII", "section_path": "TABLEII", "source_type": "table", "text": "Table evidence."},
        {"chunk_id": "table5", "section_name": "TABLEV", "section_path": "TABLEV", "source_type": "table", "text": "Table evidence."},
        {"chunk_id": "table7", "section_name": "TABLEVII", "section_path": "TABLEVII", "source_type": "text", "text": "Table title noise."},
        {"chunk_id": "formula", "section_name": "|M1 ∪M2|", "section_path": "|M1 ∪M2|", "source_type": "text", "text": "Formula artifact."},
        {"chunk_id": "n", "section_name": "N", "section_path": "N", "source_type": "text", "text": "Formula variable noise with accuracy token."},
        {"chunk_id": "fig_title", "section_name": "Figure 2 Comparison", "section_path": "Figure 2 Comparison", "source_type": "text", "text": "Figure title artifact."},
        {"chunk_id": "refs_fig", "section_name": "REFERENCES Figure 7", "section_path": "REFERENCES Figure 7", "source_type": "figure", "text": "Reference figure artifact."},
    ]

    split = note_logical_and_artifact_sections(evidence)

    assert "I. INTRODUCTION" in split["retrieved_sections"]
    assert "III. METHOD" in split["retrieved_sections"]
    assert "TABLEII" not in split["retrieved_sections"]
    assert "TABLEV" not in split["retrieved_sections"]
    assert "TABLEVII" not in split["retrieved_sections"]
    assert "|M1 ∪M2|" not in split["retrieved_sections"]
    assert "N" not in split["retrieved_sections"]
    assert "Figure 2 Comparison" not in split["retrieved_sections"]
    assert "TABLEII" in split["artifact_sections"]
    assert "TABLEV" in split["artifact_sections"]
    assert "TABLEVII" in split["artifact_sections"]
    assert "|M1 ∪M2|" in split["artifact_sections"]
    assert "N" in split["artifact_sections"]


def test_numbered_body_sentence_is_not_section_heading() -> None:
    assert _is_section_heading("1 Given that our model takes into account historical observations") is False
    assert _is_section_heading("1 Introduction") is True
    assert _is_section_heading("2.1 Method") is True


def test_body_sentence_and_abstract_line_break_are_not_section_headings() -> None:
    assert _is_section_heading("model generalization capabilities. These findings highlight the") is False
    assert _is_section_heading("Abstract—Brain–computer interface (BCI) offers a direct com-") is False
    assert _is_section_heading("Materials and Methods") is True
    assert _is_section_heading("Experimental Setup") is True
    assert _is_section_heading("References") is True


def test_typical_english_paper_sections_are_detected_without_pseudo_sections() -> None:
    titles = [
        "Abstract",
        "model generalization capabilities. These findings highlight the",
        "1 Introduction",
        "Related Work",
        "Materials and Methods",
        "Experimental Setup",
        "Results",
        "Discussion",
        "Conclusion",
        "References",
    ]
    blocks = [
        {
            "block_id": f"b{idx}",
            "paper_id": "paper",
            "page_number": max(1, idx // 2),
            "text": title,
            "bbox": [72, 72 + idx * 20, 300, 88 + idx * 20],
            "font_size": 12,
            "max_font_size": 12,
            "avg_font_size": 12,
            "bold": title[0].isupper(),
            "uppercase_ratio": 0,
            "is_header": False,
            "is_footer": False,
        }
        for idx, title in enumerate(titles, start=1)
    ]

    sections = _detect_sections("paper", blocks)
    normalized = {section["normalized_name"] for section in sections}
    detected_titles = {section["title"] for section in sections}

    assert {"abstract", "introduction", "related_work", "method", "experiment", "result", "discussion", "conclusion", "references"} <= normalized
    assert "model generalization capabilities. These findings highlight the" not in detected_titles
    assert len(sections) >= 7
