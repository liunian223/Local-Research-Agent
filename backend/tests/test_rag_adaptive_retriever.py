from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from database import connect
from tests.test_acceptance import make_multipage_pdf, post_pdf


def test_adaptive_retriever_downweights_abstract_for_method(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_multipage_pdf(
            tmp_path,
            "adaptive_method.pdf",
            [
                "Adaptive Paper\nTeam\nAbstract\nThis abstract says the method is only a broad clue.\nKeywords: rag",
                "1 Introduction\nBackground starts here.",
                "2 Method\nThe method uses block-level abstract isolation and rule-weighted reranking.",
            ],
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        response = client.post(
            "/api/chat/message",
            json={"message": "What method does this paper use?", "current_paper_id": paper_id, "chat_scope": "paper_only"},
        )
        assert response.status_code == 200
        retrieval = response.json()["execution"]["retrieval"]
        assert retrieval["retrieval_mode"] == "simple_retrieve_rerank"
        assert retrieval["query_analysis"]["abstract_mode"] == "downweight"
        assert retrieval["abstract_control"]["abstract_penalty_applied"] is True


def test_adaptive_retriever_complex_payload_has_coverage(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_multipage_pdf(
            tmp_path,
            "adaptive_complex.pdf",
            [
                "Adaptive Complex Paper\nTeam\nAbstract\nThis paper has method and experiment clues.\nKeywords: rag",
                "2 Method\nThe method uses section-targeted retrieval.",
                "3 Experiments\nThe experiment uses synthetic and real datasets.",
                "4 Results\nThe results report better grounding.",
            ],
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        response = client.post(
            "/api/chat/message",
            json={"message": "这篇论文最值得复现的部分是什么，为什么？", "current_paper_id": paper_id, "chat_scope": "paper_only"},
        )
        assert response.status_code == 200
        execution = response.json()["execution"]
        assert execution["retrieval"]["retrieval_mode"] == "complex_planned_retrieval"
        assert execution["retrieval"]["query_analysis"]["needs_decomposition"] is True
        assert "coverage_check" in execution["retrieval"]
        assert "abstract_chunks" in execution["evidence_bundle"]


def test_abstract_chunks_are_persisted_separately(tmp_path: Path) -> None:
    with TestClient(app) as client:
        pdf = make_multipage_pdf(
            tmp_path,
            "adaptive_abstract.pdf",
            [
                "Abstract Persist Paper\nTeam\nAbstract\nThis abstract must be isolated from body chunks.\nKeywords: rag",
                "1 Introduction\nThis body repeats: This abstract must be isolated from body chunks.",
            ],
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        with connect() as conn:
            abstract_chunk = conn.execute(
                "SELECT * FROM document_chunks WHERE paper_id = ? AND is_abstract = 1 LIMIT 1",
                (paper_id,),
            ).fetchone()
            body_chunk = conn.execute(
                "SELECT * FROM document_chunks WHERE paper_id = ? AND COALESCE(is_abstract, 0) = 0 AND chunk_role = 'body' LIMIT 1",
                (paper_id,),
            ).fetchone()
        assert abstract_chunk is not None
        assert body_chunk is not None
        assert "Keywords" not in abstract_chunk["content"]
