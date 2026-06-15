from __future__ import annotations

from typing import Any


POLICY_RULES: dict[str, dict[str, set[str]]] = {
    "Knowledge RAG Agent": {
        "file": {"save_uploaded_pdf", "read_pdf_text", "write_parsed_text"},
        "database": {"find_existing_paper", "insert_paper", "insert_chunks", "delete_paper_artifacts", "update_paper_status", "list_papers_by_folder"},
        "rag": {"parse_layout_document", "build_vector_index", "adaptive_retrieve", "retrieve_structured_evidence"},
        "a2a": {"*"},
    },
    "Note Skill Agent": {
        "skills": {"run_deep_paper_note_skill"},
        "file": {"write_markdown_note", "copy_pdf_to_obsidian", "read_markdown_note"},
        "database": {"insert_note", "insert_note_chunks", "update_paper_status"},
        "rag": {"build_note_vector_index"},
        "llm": {"model_chat", "model_note_generation"},
        "a2a": {"*"},
    },
    "Harness": {
        "file": {"*"},
        "database": {"*"},
        "rag": {"*"},
        "skills": {"*"},
        "llm": {"*"},
        "a2a": {"*"},
    },
}


DENY_REASONS = {
    ("Knowledge RAG Agent", "skills"): "Knowledge RAG Agent retrieves/imports evidence and cannot run skills.",
    ("Note Skill Agent", "database.insert_paper"): "Note Skill Agent cannot write papers table.",
    ("Note Skill Agent", "file.save_uploaded_pdf"): "Note Skill Agent cannot save uploaded PDFs.",
    ("finish_node", "*"): "finish_node cannot call business tools.",
}


def check_tool_policy(agent_name: str, server_name: str, tool_name: str) -> dict[str, Any]:
    server_rules = POLICY_RULES.get(agent_name, {})
    allowed_tools = server_rules.get(server_name, set())
    allowed = "*" in allowed_tools or tool_name in allowed_tools
    action = f"{server_name}.{tool_name}"
    reason = f"{agent_name} can call {action}" if allowed else _deny_reason(agent_name, server_name, tool_name)
    return {
        "allowed": allowed,
        "agent": agent_name,
        "server_name": server_name,
        "tool_name": tool_name,
        "action": action,
        "reason": reason,
    }


def _deny_reason(agent_name: str, server_name: str, tool_name: str) -> str:
    return (
        DENY_REASONS.get((agent_name, f"{server_name}.{tool_name}"))
        or DENY_REASONS.get((agent_name, server_name))
        or DENY_REASONS.get((agent_name, "*"))
        or f"{agent_name} is not allowed to call {server_name}.{tool_name}"
    )


AGENT_TOOL_POLICY = POLICY_RULES
