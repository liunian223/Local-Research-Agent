from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import harness.runtime as runtime
from app import app
from tests.test_acceptance import make_pdf


def test_upload_and_chat_endpoints_call_harness_runtime(monkeypatch, tmp_path: Path) -> None:
    calls = {"upload": 0, "chat": 0}

    def fake_upload_task(**kwargs):
        calls["upload"] += 1
        return {
            "task_id": "task_upload",
            "answer": "uploaded",
            "message_type": "paper_imported",
            "current_paper": {"paper_id": "paper_1", "title": "Paper"},
            "artifacts": {},
            "execution": {"harness": {"runtime_status": "done"}},
        }

    def fake_chat_task(**kwargs):
        calls["chat"] += 1
        return {
            "task_id": "task_chat",
            "answer": "answered",
            "message_type": "assistant_answer",
            "current_paper": None,
            "artifacts": {},
            "execution": {"harness": {"runtime_status": "done"}},
        }

    monkeypatch.setattr(runtime, "run_upload_task", fake_upload_task)
    monkeypatch.setattr("app.run_upload_task", fake_upload_task)
    monkeypatch.setattr(runtime, "run_chat_task", fake_chat_task)
    monkeypatch.setattr("app.run_chat_task", fake_chat_task)

    pdf = make_pdf(tmp_path, "runtime_entrypoint.pdf", "Runtime Entrypoint\nAbstract\ncontent")
    with TestClient(app) as client, pdf.open("rb") as handle:
        upload = client.post(
            "/api/chat/upload",
            data={"current_folder_id": "folder_all", "session_id": "session_default"},
            files={"file": (pdf.name, handle, "application/pdf")},
        )
        assert upload.status_code == 200
        assert upload.json()["execution"]["harness"]["runtime_status"] == "done"

        chat = client.post("/api/chat/message", json={"message": "hello", "chat_scope": "global_library"})
        assert chat.status_code == 200
        assert chat.json()["execution"]["harness"]["runtime_status"] == "done"

    assert calls == {"upload": 1, "chat": 1}
