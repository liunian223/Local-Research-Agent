from __future__ import annotations

from harness.context_manager import context_pack_strategy
from graph.builder import initial_phase, standard_flow
from harness.graph_runner import run_upload_agent_graph


def test_harness_runtime_maps_task_to_phase_and_context_strategy() -> None:
    assert initial_phase("import_and_note") == "IMPORT_PAPER"
    assert standard_flow("paper_chat")[0]["node"] == "coordinator_node"
    assert context_pack_strategy("generate_note") == "note_evidence_bundle_first"
    assert context_pack_strategy("global_chat", "global_library") == "global_evidence_bundle_first"


def test_harness_graph_runner_owns_upload_graph_trace(monkeypatch) -> None:
    traces: list[dict[str, object]] = []

    def fake_log_trace(conn, task_id, step_index, node_name, agent_name, action, summary):
        traces.append(
            {
                "step_index": step_index,
                "node_name": node_name,
                "agent_name": agent_name,
                "action": action,
                "summary": summary,
            }
        )

    monkeypatch.setattr("harness.graph_runner.log_trace", fake_log_trace)

    def import_handler(state, gateway):
        state["paper"] = {"id": "paper_1", "title": "Paper", "file_path": "paper.pdf"}
        state["phase"] = "REQUEST_EVIDENCE"
        return state

    def retrieve_handler(state, gateway):
        state["rag_evidence"] = [{"text": "evidence"}]
        state["phase"] = "EVIDENCE_READY"
        return state

    def note_handler(state, gateway):
        state["answer"] = "note generated"
        state["message_type"] = "note_generated"
        state["phase"] = "NOTE_READY"
        return state

    def answer_handler(state, gateway):
        state["phase"] = "ERROR"
        return state

    final_state = run_upload_agent_graph(
        conn=object(),
        task_id="task_1",
        task_type="import_and_note",
        file_bytes=b"%PDF-1.4",
        file_name="paper.pdf",
        folder_id="folder_all",
        message="note",
        import_handler=import_handler,
        retrieve_handler=retrieve_handler,
        generate_note_handler=note_handler,
        answer_chat_handler=answer_handler,
    )

    assert final_state["status"] == "done"
    assert final_state["message_type"] == "note_generated"
    assert final_state["context_pack_strategy"] == "note_evidence_bundle_first"
    assert [trace["node_name"] for trace in traces] == [
        "coordinator_node",
        "knowledge_rag_agent_node",
        "knowledge_rag_agent_node",
        "note_skill_agent_node",
        "finish_node",
    ]
