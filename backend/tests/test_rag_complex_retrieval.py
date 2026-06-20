from __future__ import annotations

from adaptive_rag.evidence_checker import check_coverage
from adaptive_rag.reranker import rerank


def test_coverage_check_reports_missing_sections_without_body_evidence() -> None:
    evidence = [
        {
            "section_name": "Abstract",
            "section_path": "Abstract",
            "is_abstract": True,
            "chunk_role": "abstract",
            "text": "The abstract mentions experiments.",
        }
    ]
    analysis = {"complexity": "complex", "target_sections": ["method", "experiment"]}
    coverage = check_coverage(evidence, analysis)
    assert coverage["sufficient"] is False
    assert coverage["missing_sections"] == ["method", "experiment"]
    assert coverage["needs_second_pass"] is True


def test_reranker_records_breakdown_and_rewards_target_section() -> None:
    candidates = [
        {"chunk_id": "intro", "score": 1.0, "section_name": "Introduction", "text": "method model"},
        {"chunk_id": "method", "score": 1.0, "section_name": "Method", "section_path": "2 Method", "text": "method model"},
    ]
    evidence, meta = rerank("What method does this paper use?", candidates, {"intent": "method", "target_sections": ["method"], "abstract_mode": "downweight"}, 2)
    assert meta["score_breakdown_available"] is True
    assert evidence[0]["chunk_id"] == "method"
    assert evidence[0]["score_breakdown"]["section_bonus"] > evidence[1]["score_breakdown"]["section_bonus"]


def test_reranker_keeps_body_evidence_above_abstract_for_complex_question() -> None:
    candidates = [
        {"chunk_id": "abstract", "score": 3.0, "section_name": "Abstract", "is_abstract": True, "chunk_role": "abstract", "text": "method experiment result"},
        {"chunk_id": "method", "score": 1.0, "section_name": "Method", "section_path": "2 Method", "text": "method experiment result"},
    ]
    evidence, _ = rerank(
        "Compare the method and experiment result",
        candidates,
        {"intent": "comparison", "complexity": "complex", "target_sections": ["method", "experiment", "result"], "abstract_mode": "downweight"},
        2,
    )
    assert evidence[0]["chunk_id"] == "method"
    assert evidence[1]["score_breakdown"]["abstract_penalty"] < 1.0
