from __future__ import annotations

from adaptive_rag.query_analyzer import analyze_query


def test_query_analyzer_simple_method_downweights_abstract() -> None:
    analysis = analyze_query("What method does this paper use?", "paper_only")
    assert analysis["complexity"] == "simple"
    assert analysis["intent"] == "method"
    assert analysis["abstract_mode"] == "downweight"
    assert analysis["needs_decomposition"] is False


def test_query_analyzer_complex_reproduction_plans_sub_questions() -> None:
    analysis = analyze_query("这篇论文最值得复现的部分是什么，为什么？", "paper_only")
    assert analysis["complexity"] == "complex"
    assert analysis["intent"] == "reproduction"
    assert analysis["needs_decomposition"] is True
    assert analysis["sub_questions"]


def test_query_analyzer_abstract_question_includes_abstract() -> None:
    analysis = analyze_query("这篇论文摘要讲了什么？", "paper_only")
    assert analysis["intent"] == "abstract"
    assert analysis["abstract_mode"] == "include"
