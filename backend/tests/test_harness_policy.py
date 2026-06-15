from __future__ import annotations

from harness.policy import check_tool_policy


def test_harness_policy_allows_and_denies_expected_tools() -> None:
    assert check_tool_policy("Knowledge RAG Agent", "rag", "adaptive_retrieve")["allowed"] is True
    assert check_tool_policy("Knowledge RAG Agent", "database", "insert_paper")["allowed"] is True
    assert check_tool_policy("Knowledge RAG Agent", "database", "insert_chunks")["allowed"] is True
    assert check_tool_policy("Knowledge RAG Agent", "database", "delete_paper_artifacts")["allowed"] is True
    assert check_tool_policy("Knowledge RAG Agent", "skills", "run_deep_paper_note_skill")["allowed"] is False
    assert check_tool_policy("Note Skill Agent", "skills", "run_deep_paper_note_skill")["allowed"] is True
    assert check_tool_policy("Note Skill Agent", "database", "insert_paper")["allowed"] is False
    assert check_tool_policy("finish_node", "rag", "adaptive_retrieve")["allowed"] is False
