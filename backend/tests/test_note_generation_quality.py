from __future__ import annotations

import harness.agent_service as agent_service
from harness.agent_service import NOTE_RETRIEVAL_PLAN, assess_note_evidence_coverage, has_partial_note_fallback, retrieve_note_plan_evidence
from layout_parser import _is_section_heading


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


def test_numbered_body_sentence_is_not_section_heading() -> None:
    assert _is_section_heading("1 Given that our model takes into account historical observations") is False
    assert _is_section_heading("1 Introduction") is True
    assert _is_section_heading("2.1 Method") is True
