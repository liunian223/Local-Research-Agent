from __future__ import annotations

from adaptive_rag.abstract_detector import detect_abstract


def test_detect_english_abstract_marks_section_and_blocks() -> None:
    document = {
        "paper_id": "paper_test",
        "sections": [
            {
                "section_id": "sec_abs",
                "title": "Abstract",
                "normalized_name": "abstract",
                "section_path": "Abstract",
                "page_start": 1,
                "page_end": 1,
                "block_ids": ["b1", "b2"],
            },
            {
                "section_id": "sec_intro",
                "title": "1 Introduction",
                "normalized_name": "introduction",
                "section_path": "1 Introduction",
                "page_start": 1,
                "page_end": 2,
                "block_ids": ["b3"],
            },
        ],
        "text_blocks": [
            {"block_id": "b1", "text": "Abstract\nThis paper proposes an adaptive RAG pipeline.", "page_number": 1},
            {"block_id": "b2", "text": "Keywords: RAG", "page_number": 1},
            {"block_id": "b3", "text": "1 Introduction\nThe body starts here.", "page_number": 1},
        ],
    }
    result = detect_abstract(document)
    assert result["has_abstract"] is True
    assert result["section_id"] == "sec_abs"
    assert "Introduction" not in result["abstract_text"]
    assert document["sections"][0]["is_abstract"] is True
    assert document["text_blocks"][0]["is_abstract"] is True


def test_detect_chinese_abstract_stops_before_keywords() -> None:
    document = {
        "paper_id": "paper_cn",
        "sections": [
            {
                "section_id": "sec_abs",
                "title": "摘要",
                "normalized_name": "abstract",
                "section_path": "摘要",
                "page_start": 1,
                "page_end": 1,
                "block_ids": ["b1"],
            }
        ],
        "text_blocks": [
            {"block_id": "b1", "text": "摘要\n本文提出一种方法。\n关键词：检索\n1 引言\n正文。", "page_number": 1}
        ],
    }
    result = detect_abstract(document)
    assert result["has_abstract"] is True
    assert "关键词" not in result["abstract_text"]
    assert "引言" not in result["abstract_text"]
