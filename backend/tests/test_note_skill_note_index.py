from __future__ import annotations

from rag import note_to_chunks


def test_note_to_chunks_marks_note_metadata() -> None:
    chunks = note_to_chunks("note_1", "paper_1", "# Note\n\n## Method\nBody text about methods.")
    assert chunks
    assert all(chunk["note_id"] == "note_1" for chunk in chunks)
    assert all(chunk["paper_id"] == "paper_1" for chunk in chunks)
