from __future__ import annotations

import hashlib
from typing import Any

import config
from rag import score_chunks


class VectorStore:
    """Optional Chroma store with local keyword fallback."""

    def __init__(self) -> None:
        self.backend = "local_keyword"
        self.collection = None
        if config.VECTOR_BACKEND.lower() == "chroma":
            try:
                import chromadb

                client = chromadb.PersistentClient(path=str(config.VECTOR_DIR))
                self.collection = client.get_or_create_collection(
                    name="local_research_agent",
                    metadata={"hnsw:space": "cosine"},
                )
                self.backend = "chroma"
            except Exception:
                self.collection = None
                self.backend = "local_keyword"

    def index_chunks(self, chunks: list[dict[str, Any]], source_type: str, paper_id: str, note_id: str = "") -> dict[str, Any]:
        if not chunks:
            return {"backend": self.backend, "indexed": 0, "status": "skipped"}
        if self.collection is None:
            return {"backend": self.backend, "indexed": len(chunks), "status": "fallback_index_recorded"}
        ids = []
        docs = []
        metas = []
        for chunk in chunks:
            vector_id = chunk.get("vector_id") or chunk.get("id") or stable_id(paper_id, note_id, chunk.get("text", ""))
            ids.append(vector_id)
            docs.append(chunk.get("text", ""))
            metas.append(
                {
                    "source_type": source_type,
                    "paper_id": paper_id,
                    "note_id": note_id,
                    "section_name": chunk.get("section_name") or "Body",
                    "chunk_id": chunk.get("id") or vector_id,
                    "chunk_index": int(chunk.get("chunk_index") or 0),
                }
            )
        try:
            self.collection.upsert(ids=ids, documents=docs, metadatas=metas)
            return {"backend": self.backend, "indexed": len(chunks), "status": "done"}
        except Exception as exc:
            self.collection = None
            self.backend = "local_keyword"
            return {
                "backend": self.backend,
                "indexed": len(chunks),
                "status": "fallback_index_recorded",
                "error": str(exc)[:300],
            }

    def retrieve(self, query: str, rows: list[dict[str, Any]], top_k: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        top_k = top_k or config.RAG_TOP_K
        if self.collection is None:
            return score_chunks(query, rows, top_k), {"backend": self.backend, "fallback": True}

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
                        "text": (docs[rank - 1] or "")[: config.MAX_EVIDENCE_CHARS],
                    }
                )
            return evidence, {"backend": self.backend, "fallback": False}
        except Exception as exc:
            return score_chunks(query, rows, top_k), {"backend": "local_keyword", "fallback": True, "error": str(exc)[:300]}


def stable_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"vec_{digest}"


def build_where(rows: list[dict[str, Any]]) -> dict[str, Any]:
    chunk_ids = sorted({row.get("id") or row.get("chunk_id") for row in rows if row.get("id") or row.get("chunk_id")})
    if chunk_ids:
        return {"chunk_id": {"$in": chunk_ids}}
    return {}


VECTOR_STORE = VectorStore()
