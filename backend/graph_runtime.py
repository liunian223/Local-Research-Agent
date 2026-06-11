from graph.builder import (
    NODE_LIMITS,
    PHASES,
    TASK_INITIAL_PHASE,
    initial_phase,
    route_after_coordinator,
    route_after_knowledge,
    route_after_note_skill,
)


def standard_flow(task_type: str) -> list[dict[str, str]]:
    if task_type == "import_paper":
        return [
            {"node": "coordinator_node", "phase": "IMPORT_PAPER"},
            {"node": "knowledge_rag_agent_node", "phase": "IMPORT_DONE"},
            {"node": "finish_node", "phase": "FINISH"},
        ]
    if task_type == "import_and_note":
        return [
            {"node": "coordinator_node", "phase": "IMPORT_PAPER"},
            {"node": "knowledge_rag_agent_node", "phase": "REQUEST_EVIDENCE"},
            {"node": "knowledge_rag_agent_node", "phase": "EVIDENCE_READY"},
            {"node": "note_skill_agent_node", "phase": "NOTE_READY"},
            {"node": "finish_node", "phase": "FINISH"},
        ]
    if task_type == "generate_note":
        return [
            {"node": "coordinator_node", "phase": "REQUEST_EVIDENCE"},
            {"node": "knowledge_rag_agent_node", "phase": "EVIDENCE_READY"},
            {"node": "note_skill_agent_node", "phase": "NOTE_READY"},
            {"node": "finish_node", "phase": "FINISH"},
        ]
    return [
        {"node": "coordinator_node", "phase": "REQUEST_EVIDENCE"},
        {"node": "knowledge_rag_agent_node", "phase": "EVIDENCE_READY"},
        {"node": "note_skill_agent_node", "phase": "ANSWER_READY"},
        {"node": "finish_node", "phase": "FINISH"},
    ]


def validate_node_visits(visited: list[str]) -> tuple[bool, str]:
    counts: dict[str, int] = {}
    for node in visited:
        counts[node] = counts.get(node, 0) + 1
        if counts[node] > NODE_LIMITS.get(node, 1):
            return False, f"Node visit limit exceeded: {node}"
    return True, ""
