from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from tests.test_acceptance import make_pdf, post_pdf


def test_execution_payload_contains_harness_runtime(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(tmp_path, "harness_payload.pdf", "Harness Paper\nTeam\nAbstract\nHarness runtime payload.")
        response = post_pdf(client, pdf)
        assert response.status_code == 200
        harness = response.json()["execution"]["harness"]
        assert harness["task_id"]
        assert harness["run_id"]
        assert harness["runtime_status"] == "done"
        assert "policy_checks" in harness
        assert harness["tool_summary"]["total_calls"] > 0
        assert harness["redaction"]["enabled"] is True
