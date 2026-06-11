from __future__ import annotations

from typing import Any

from vector_store import VECTOR_STORE


def build_vector_index(chunks: list[dict[str, Any]], paper_id: str) -> dict[str, Any]:
    return VECTOR_STORE.index_chunks(chunks, "paper", paper_id)


def build_note_vector_index(chunks: list[dict[str, Any]], paper_id: str, note_id: str) -> dict[str, Any]:
    return VECTOR_STORE.index_chunks(chunks, "note", paper_id, note_id)


def retrieve_chunks(query: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return VECTOR_STORE.retrieve(query, rows)


retrieve_note_blocks = retrieve_chunks
retrieve_paper_and_note = retrieve_chunks
retrieve_global_knowledge = retrieve_chunks
