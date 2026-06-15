from __future__ import annotations

from adaptive_rag.evidence_checker import check_coverage


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
