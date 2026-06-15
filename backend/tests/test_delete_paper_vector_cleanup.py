from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from tests.test_acceptance import make_pdf, post_pdf


def test_delete_paper_invokes_vector_cleanup(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_delete_by_paper_id(paper_id: str) -> dict:
        calls.append(("paper", paper_id))
        return {"backend": "test", "status": "done", "deleted_count": 2}

    def fake_delete_by_note_id(note_id: str) -> dict:
        calls.append(("note", note_id))
        return {"backend": "test", "status": "done", "deleted_count": 1}

    monkeypatch.setattr("app.VECTOR_STORE.delete_by_paper_id", fake_delete_by_paper_id)
    monkeypatch.setattr("app.VECTOR_STORE.delete_by_note_id", fake_delete_by_note_id)

    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "vector_cleanup.pdf",
            "Vector Cleanup Paper\nAlice\n2026\nAbstract\nThis paper is deleted with vector cleanup.",
        )
        upload = post_pdf(client, pdf, message="generate note")
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        deleted = client.delete(f"/api/papers/{paper_id}")

    assert deleted.status_code == 200
    body = deleted.json()
    assert body["deleted_papers"] == 1
    assert ("paper", paper_id) in calls
    assert any(call[0] == "note" for call in calls)
    assert body["vector_cleanup"]


def test_delete_paper_continues_when_vector_cleanup_fails(monkeypatch, tmp_path: Path) -> None:
    def failing_delete_by_paper_id(paper_id: str) -> dict:
        raise RuntimeError("vector unavailable")

    monkeypatch.setattr("app.VECTOR_STORE.delete_by_paper_id", failing_delete_by_paper_id)
    monkeypatch.setattr("app.VECTOR_STORE.delete_by_note_id", lambda note_id: {"backend": "test", "status": "done", "deleted_count": 0})

    with TestClient(app) as client:
        pdf = make_pdf(
            tmp_path,
            "vector_cleanup_failure.pdf",
            "Vector Cleanup Failure\nAlice\n2026\nAbstract\nThis paper deletion should continue.",
        )
        upload = post_pdf(client, pdf)
        assert upload.status_code == 200
        paper_id = upload.json()["current_paper"]["paper_id"]

        deleted = client.delete(f"/api/papers/{paper_id}")
        assert deleted.status_code == 200
        assert client.get(f"/api/papers/{paper_id}").status_code == 404
        assert deleted.json()["vector_cleanup"][0]["status"] == "failed"
