from __future__ import annotations

from typing import Callable

from graph.state import AgentState

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency fallback.
    END = None
    StateGraph = None


PHASES = {
    "START",
    "ROUTE_TASK",
    "IMPORT_PAPER",
    "IMPORT_DONE",
    "REQUEST_EVIDENCE",
    "EVIDENCE_READY",
    "GENERATE_NOTE",
    "NOTE_READY",
    "ANSWER_CHAT",
    "ANSWER_READY",
    "FINISH",
    "ERROR",
}

TASK_INITIAL_PHASE = {
    "import_paper": "IMPORT_PAPER",
    "import_and_note": "IMPORT_PAPER",
    "generate_note": "REQUEST_EVIDENCE",
    "paper_chat": "REQUEST_EVIDENCE",
    "global_chat": "REQUEST_EVIDENCE",
}

NODE_LIMITS = {
    "coordinator_node": 1,
    "knowledge_rag_agent_node": 3,
    "note_skill_agent_node": 3,
    "finish_node": 1,
}


def initial_phase(task_type: str) -> str:
    return TASK_INITIAL_PHASE.get(task_type, "REQUEST_EVIDENCE")


def guard_node_visit(state: AgentState, node_name: str) -> AgentState:
    counts = state.setdefault("node_visit_count", {})
    counts[node_name] = counts.get(node_name, 0) + 1
    if counts[node_name] > NODE_LIMITS.get(node_name, 1):
        state["phase"] = "ERROR"
        state["error"] = f"Node {node_name} exceeded max visits."
        state["status"] = "failed"
    return state


def coordinator_node(state: AgentState) -> AgentState:
    guard_node_visit(state, "coordinator_node")
    if state.get("phase") in {None, "START", "ROUTE_TASK"}:
        state["phase"] = initial_phase(state.get("task_type", ""))
    state["status"] = state.get("status") or "running"
    return state


def route_after_coordinator(state: AgentState) -> str:
    phase = state.get("phase")
    if phase in {"IMPORT_PAPER", "REQUEST_EVIDENCE"}:
        return "knowledge_rag_agent_node"
    if phase == "ERROR":
        return "finish_node"
    return "finish_node"


def route_after_knowledge(state: AgentState) -> str:
    task_type = state.get("task_type")
    phase = state.get("phase")
    if phase == "ERROR":
        return "finish_node"
    if task_type == "import_paper" and phase == "IMPORT_DONE":
        return "finish_node"
    if task_type == "import_and_note" and phase == "REQUEST_EVIDENCE":
        return "knowledge_rag_agent_node"
    if phase == "EVIDENCE_READY":
        return "note_skill_agent_node"
    return "finish_node"


def route_after_note_skill(state: AgentState) -> str:
    phase = state.get("phase")
    if phase == "ERROR":
        return "finish_node"
    if phase == "REQUEST_EVIDENCE":
        return "knowledge_rag_agent_node"
    if phase in {"NOTE_READY", "ANSWER_READY"}:
        return "finish_node"
    return "finish_node"


def finish_node(state: AgentState) -> AgentState:
    guard_node_visit(state, "finish_node")
    if state.get("phase") == "ERROR":
        state["status"] = "failed"
        state["answer"] = state.get("answer") or "任务执行中止：检测到异常循环。"
    else:
        state["phase"] = "FINISH"
        state["status"] = "done"
    return state


def run_graph_fallback(
    initial_state: AgentState,
    knowledge_node: Callable[[AgentState], AgentState],
    note_node: Callable[[AgentState], AgentState],
) -> AgentState:
    state = coordinator_node(initial_state)
    next_node = route_after_coordinator(state)
    recursion_limit = 12
    steps = 0
    while next_node != "finish_node" and steps < recursion_limit:
        steps += 1
        if next_node == "knowledge_rag_agent_node":
            state = knowledge_node(state)
            next_node = route_after_knowledge(state)
            continue
        if next_node == "note_skill_agent_node":
            state = note_node(state)
            next_node = route_after_note_skill(state)
            continue
        state["phase"] = "ERROR"
        state["error"] = f"Unknown graph node: {next_node}"
        break
    if steps >= recursion_limit:
        state["phase"] = "ERROR"
        state["error"] = "Graph recursion limit exceeded."
        state["answer"] = "任务执行中止：检测到异常循环。"
    return finish_node(state)


def build_langgraph_app(
    knowledge_node: Callable[[AgentState], AgentState],
    note_node: Callable[[AgentState], AgentState],
) -> object | None:
    if StateGraph is None or END is None:
        return None

    graph = StateGraph(dict)
    graph.add_node("coordinator_node", coordinator_node)
    graph.add_node("knowledge_rag_agent_node", knowledge_node)
    graph.add_node("note_skill_agent_node", note_node)
    graph.add_node("finish_node", finish_node)

    graph.set_entry_point("coordinator_node")
    graph.add_conditional_edges(
        "coordinator_node",
        route_after_coordinator,
        {
            "knowledge_rag_agent_node": "knowledge_rag_agent_node",
            "finish_node": "finish_node",
        },
    )
    graph.add_conditional_edges(
        "knowledge_rag_agent_node",
        route_after_knowledge,
        {
            "knowledge_rag_agent_node": "knowledge_rag_agent_node",
            "note_skill_agent_node": "note_skill_agent_node",
            "finish_node": "finish_node",
        },
    )
    graph.add_conditional_edges(
        "note_skill_agent_node",
        route_after_note_skill,
        {
            "knowledge_rag_agent_node": "knowledge_rag_agent_node",
            "finish_node": "finish_node",
        },
    )
    graph.add_edge("finish_node", END)
    return graph.compile()


def run_graph(
    initial_state: AgentState,
    knowledge_node: Callable[[AgentState], AgentState],
    note_node: Callable[[AgentState], AgentState],
) -> AgentState:
    app = build_langgraph_app(knowledge_node, note_node)
    if app is None:
        return run_graph_fallback(initial_state, knowledge_node, note_node)
    try:
        result = app.invoke(initial_state, {"recursion_limit": 12})
    except Exception as exc:
        failed_state = dict(initial_state)
        failed_state["phase"] = "ERROR"
        failed_state["status"] = "failed"
        failed_state["error"] = f"LangGraph execution failed: {exc}"
        return run_graph_fallback(failed_state, knowledge_node, note_node)
    return result
