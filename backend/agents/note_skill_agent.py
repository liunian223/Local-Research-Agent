from __future__ import annotations

from typing import Callable

from graph.builder import guard_node_visit
from graph.state import AgentState


def note_skill_agent_node(
    state: AgentState,
    generate_note_handler: Callable[[AgentState], AgentState],
    answer_chat_handler: Callable[[AgentState], AgentState],
) -> AgentState:
    guard_node_visit(state, "note_skill_agent_node")
    if state.get("phase") == "ERROR":
        return state
    task_type = state.get("task_type")
    phase = state.get("phase")
    if phase == "EVIDENCE_READY" and task_type in {"generate_note", "import_and_note"}:
        return generate_note_handler(state)
    if phase == "EVIDENCE_READY" and task_type in {"paper_chat", "global_chat", "vision_chat"}:
        return answer_chat_handler(state)
    if phase == "REQUEST_EVIDENCE":
        state["needs_evidence"] = True
        return state
    state["phase"] = "ERROR"
    state["error"] = f"Note Skill Agent received unsupported phase: {phase}"
    state["status"] = "failed"
    return state
