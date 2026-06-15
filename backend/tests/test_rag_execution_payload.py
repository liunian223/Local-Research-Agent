from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from tests.test_acceptance import make_multipage_pdf, post_pdf


def test_execution_payload_contains_adaptive_rag_fields(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_multipage_pdf(
            tmp_path,
            "adaptive_payload.pdf",
            [
                "Payload Paper\nTeam\nAbstract\nThis paper tests execution payloads.\nKeywords: rag",
                "2 Method\nThe method records query analysis and coverage.",
            ],
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
        assert execution["retrieval"]["query_analysis"]
        assert execution["retrieval"]["abstract_control"]
        assert execution["retrieval"]["rerank"]
        assert execution["retrieval"]["coverage_check"]
        assert "abstract_chunks" in execution["evidence_bundle"]
        assert isinstance(execution["rag_evidence"], list)
