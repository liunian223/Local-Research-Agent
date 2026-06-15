from __future__ import annotations

from harness.context_manager import context_pack_strategy
from graph.builder import initial_phase, standard_flow


def test_harness_runtime_maps_task_to_phase_and_context_strategy() -> None:
    assert initial_phase("import_and_note") == "IMPORT_PAPER"
    assert standard_flow("paper_chat")[0]["node"] == "coordinator_node"
    assert context_pack_strategy("generate_note") == "note_evidence_bundle_first"
    assert context_pack_strategy("global_chat", "global_library") == "global_evidence_bundle_first"
