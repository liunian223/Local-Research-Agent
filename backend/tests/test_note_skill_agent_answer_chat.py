from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from tests.test_acceptance import make_pdf, post_pdf


def test_answer_chat_uses_grouped_evidence_pipeline(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "note_agent_answer.pdf",
            "Answer Paper\nTeam\nAbstract\nThis paper discusses grouped evidence.\n2 Method\nThe method uses grouped evidence prompts.",
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]
        response = client.post(
            "/api/chat/message",
            json={"message": "Explain the method", "current_paper_id": paper_id, "chat_scope": "paper_only"},
        )
        assert response.status_code == 200
        execution = response.json()["execution"]
        assert execution["evidence_bundle"]
        assert execution["retrieval"]["query_analysis"]
