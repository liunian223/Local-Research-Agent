from __future__ import annotations

from eval.rag_eval import summarize, write_markdown_report


def test_rag_eval_report_explains_insufficient_data(tmp_path) -> None:
    results = [{"id": "q1", "status": "skipped", "skip_reason": "paper_id_not_found:missing"}]
    summary = summarize(results)
    report_path = tmp_path / "rag_eval_report.md"

    write_markdown_report(report_path, summary, results, tmp_path / "eval.jsonl")

    text = report_path.read_text(encoding="utf-8")
    assert "未产生有效指标" in text
    assert "Not enough local data" in text
    assert "paper_id_not_found" in text


def test_rag_eval_report_shows_case_details(tmp_path) -> None:
    results = [
        {
            "id": "q1",
            "status": "ok",
            "query": "What method is used?",
            "paper_id": "paper_1",
            "recall@3": 1.0,
            "recall@5": 1.0,
            "mrr": 1.0,
            "evidence_hit": True,
            "first_relevant_rank": 1,
            "top_evidence_section": "Method",
            "top_evidence_score": 4,
            "selected_mode": "simple_retrieve_rerank",
        }
    ]
    summary = summarize(results)
    report_path = tmp_path / "rag_eval_report.md"

    write_markdown_report(report_path, summary, results, tmp_path / "eval.jsonl")

    text = report_path.read_text(encoding="utf-8")
    assert "Recall@3: 1.0" in text
    assert "Evidence Hit Rate: 1.0" in text
    assert "Query: What method is used?" in text
    assert "Top evidence section: Method" in text
    assert "No skipped cases." in text
