from __future__ import annotations

import builtins

from vector_store import VectorStore


def test_vector_store_records_chroma_init_fallback_reason(monkeypatch) -> None:
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "chromadb":
            raise ModuleNotFoundError("No module named 'chromadb'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("vector_store.config.VECTOR_BACKEND", "chroma")
    monkeypatch.setattr(builtins, "__import__", fake_import)

    store = VectorStore()
    status = store.backend_status()

    assert status["configured_backend"] == "chroma"
    assert status["actual_backend"] == "local_keyword"
    assert status["fallback_reason"] == "chroma_init_failed:ModuleNotFoundError"
    assert status["exception_class"] == "ModuleNotFoundError"
