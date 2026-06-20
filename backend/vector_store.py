from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import config
from rag import score_chunks


class VectorStore:
    """Optional Chroma store with local keyword fallback."""

    def __init__(self) -> None:
        self.backend = "local_keyword"
        self.collection = None
        self.init_exception_class = ""
        self.init_exception_message = ""
        self.fallback_reason = ""
        if config.VECTOR_BACKEND.lower() == "chroma":
            try:
                import chromadb

                client = chromadb.PersistentClient(path=str(config.VECTOR_DIR))
                self.collection = client.get_or_create_collection(
                    name="local_research_agent",
                    metadata={"hnsw:space": "cosine"},
                )
                self.backend = "chroma"
            except Exception as exc:
                self.collection = None
                self.backend = "local_keyword"
                self.init_exception_class = exc.__class__.__name__
                self.init_exception_message = str(exc)[:300]
                self.fallback_reason = f"chroma_init_failed:{self.init_exception_class}"
        else:
            self.fallback_reason = "configured_backend_is_not_chroma"

    def backend_config(self) -> dict[str, Any]:
        return {
            "configured_backend": config.VECTOR_BACKEND,
            "embedding_provider": config.EMBEDDING_PROVIDER,
            "embedding_model": config.OPENAI_EMBEDDING_MODEL if config.EMBEDDING_PROVIDER.lower() == "openai" else config.EMBEDDING_MODEL,
            "chroma_persist_directory": str(config.VECTOR_DIR),
        }

    def backend_status(self) -> dict[str, Any]:
        return {
            "configured_backend": config.VECTOR_BACKEND,
            "actual_backend": self.backend,
            "embedding_provider": config.EMBEDDING_PROVIDER,
            "embedding_model": config.OPENAI_EMBEDDING_MODEL if config.EMBEDDING_PROVIDER.lower() == "openai" else config.EMBEDDING_MODEL,
            "chroma_persist_directory": str(config.VECTOR_DIR),
            "chroma_persist_directory_exists": Path(config.VECTOR_DIR).exists(),
            "chroma_persist_directory_writable": _path_writable(Path(config.VECTOR_DIR)),
            "fallback": self.collection is None,
            "fallback_reason": self.fallback_reason,
            "exception_class": self.init_exception_class,
            "exception_message": self.init_exception_message,
        }

    def index_chunks(self, chunks: list[dict[str, Any]], source_type: str, paper_id: str, note_id: str = "") -> dict[str, Any]:
        if not chunks:
            return {"backend": self.backend, "indexed": 0, "status": "skipped"}
        if self.collection is None:
            return {"backend": self.backend, "indexed": len(chunks), "status": "fallback_index_recorded"}
        ids = []
        docs = []
        metas = []
        for chunk in chunks:
            text = chunk.get("text") or chunk.get("content") or ""
            vector_id = chunk.get("vector_id") or chunk.get("id") or stable_id(paper_id, note_id, text)
            ids.append(vector_id)
            docs.append(text)
            metas.append(
                {
                    "source_type": chunk.get("source_type") or source_type,
                    "paper_id": paper_id,
                    "note_id": note_id,
                    "section_name": chunk.get("section_name") or chunk.get("section_title") or "Body",
                    "section_path": chunk.get("section_path") or chunk.get("section_name") or "Body",
                    "section_id": chunk.get("section_id") or "",
                    "page_start": int(chunk.get("page_start") or 0),
                    "page_end": int(chunk.get("page_end") or 0),
                    "chunk_id": chunk.get("id") or vector_id,
                    "chunk_index": int(chunk.get("chunk_index") or 0),
                    "context_prefix": chunk.get("context_prefix") or "",
                    "section_role": chunk.get("section_role") or chunk.get("parent_section_role") or "",
                    "is_abstract": bool(chunk.get("is_abstract")),
                    "chunk_role": chunk.get("chunk_role") or "",
                    "retrieval_weight": float(chunk.get("retrieval_weight") or 1.0),
                    "title": chunk.get("title") or "",
                    "authors": chunk.get("authors") or "",
                }
            )
        try:
            self.collection.upsert(ids=ids, documents=docs, metadatas=metas)
            return {"backend": self.backend, "indexed": len(chunks), "status": "done"}
        except Exception as exc:
            self.collection = None
            self.backend = "local_keyword"
            self.init_exception_class = exc.__class__.__name__
            self.init_exception_message = str(exc)[:300]
            self.fallback_reason = f"chroma_upsert_failed:{self.init_exception_class}"
            return {
                "backend": self.backend,
                "indexed": len(chunks),
                "status": "fallback_index_recorded",
                "fallback_reason": self.fallback_reason,
                "exception_class": self.init_exception_class,
                "error": str(exc)[:300],
            }

    def retrieve(self, query: str, rows: list[dict[str, Any]], top_k: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        top_k = top_k or config.RAG_TOP_K
        if not rows:
            return [], {"backend": self.backend, "fallback": self.collection is None, "fallback_reason": self.fallback_reason}
        if self.collection is None:
            return score_chunks(query, rows, top_k), {
                "backend": self.backend,
                "fallback": True,
                "fallback_reason": self.fallback_reason,
                "exception_class": self.init_exception_class,
                "error": self.init_exception_message,
            }

        where = build_where(rows)
        try:
            result = self.collection.query(query_texts=[query], n_results=top_k, where=where or None)
            evidence = []
            ids = (result.get("ids") or [[]])[0]
            docs = (result.get("documents") or [[]])[0]
            metas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            for rank, doc_id in enumerate(ids, start=1):
                meta = metas[rank - 1] or {}
                evidence.append(
                    {
                        "rank": rank,
                        "score": distances[rank - 1] if rank - 1 < len(distances) else 0,
                        "source_type": meta.get("source_type", "paper"),
                        "paper_id": meta.get("paper_id"),
                        "note_id": meta.get("note_id"),
                        "chunk_id": meta.get("chunk_id") or doc_id,
                        "section_name": meta.get("section_name") or "Body",
                        "section_path": meta.get("section_path") or meta.get("section_name") or "Body",
                        "section_id": meta.get("section_id") or "",
                        "page_start": meta.get("page_start") or None,
                        "page_end": meta.get("page_end") or None,
                        "context_prefix": meta.get("context_prefix") or "",
                        "section_role": meta.get("section_role") or "",
                        "is_abstract": bool(meta.get("is_abstract")),
                        "chunk_role": meta.get("chunk_role") or "",
                        "retrieval_weight": meta.get("retrieval_weight") or 1.0,
                        "text": (docs[rank - 1] or "")[: config.MAX_EVIDENCE_CHARS],
                    }
                )
            return evidence, {"backend": self.backend, "fallback": False}
        except Exception as exc:
            self.collection = None
            self.backend = "local_keyword"
            self.init_exception_class = exc.__class__.__name__
            self.init_exception_message = str(exc)[:300]
            self.fallback_reason = f"chroma_query_failed:{self.init_exception_class}"
            return score_chunks(query, rows, top_k), {
                "backend": "local_keyword",
                "fallback": True,
                "fallback_reason": self.fallback_reason,
                "exception_class": self.init_exception_class,
                "error": self.init_exception_message,
            }

    def delete_by_paper_id(self, paper_id: str) -> dict[str, Any]:
        return self._delete_by_metadata("paper_id", paper_id)

    def delete_by_note_id(self, note_id: str) -> dict[str, Any]:
        return self._delete_by_metadata("note_id", note_id)

    def _delete_by_metadata(self, key: str, value: str) -> dict[str, Any]:
        if not value:
            return {"backend": self.backend, "status": "skipped", "deleted_count": 0, "message": f"missing_{key}"}
        if self.collection is None:
            return {
                "backend": self.backend,
                "status": "fallback_noop",
                "deleted_count": 0,
                "message": "Vector backend unavailable; local keyword fallback reads SQLite rows only.",
            }
        where = {key: value}
        try:
            existing = self.collection.get(where=where)
            ids = existing.get("ids") or []
            if ids:
                self.collection.delete(ids=ids)
            return {"backend": self.backend, "status": "done", "deleted_count": len(ids), "where": where}
        except Exception as exc:
            return {"backend": self.backend, "status": "failed", "deleted_count": 0, "where": where, "error": str(exc)[:300]}


def stable_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"vec_{digest}"


def build_where(rows: list[dict[str, Any]]) -> dict[str, Any]:
    chunk_ids = sorted({row.get("id") or row.get("chunk_id") for row in rows if row.get("id") or row.get("chunk_id")})
    if chunk_ids:
        return {"chunk_id": {"$in": chunk_ids}}
    return {}


def _path_writable(path: Path) -> bool:
    probe = path if path.exists() else path.parent
    return probe.exists() and os.access(probe, os.W_OK)


VECTOR_STORE = VectorStore()
