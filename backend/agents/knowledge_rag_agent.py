from __future__ import annotations

from typing import Callable

from graph.builder import guard_node_visit
from graph.state import AgentState


def knowledge_rag_agent_node(
    state: AgentState,
    import_handler: Callable[[AgentState], AgentState],
    retrieve_handler: Callable[[AgentState], AgentState],
) -> AgentState:
    guard_node_visit(state, "knowledge_rag_agent_node")
    if state.get("phase") == "ERROR":
        return state
    phase = state.get("phase")
    if phase == "IMPORT_PAPER":
        return import_handler(state)
    if phase == "REQUEST_EVIDENCE":
        return retrieve_handler(state)
    state["phase"] = "ERROR"
    state["error"] = f"Knowledge RAG Agent received unsupported phase: {phase}"
    state["status"] = "failed"
    return state
