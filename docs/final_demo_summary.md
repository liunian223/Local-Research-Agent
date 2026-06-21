# Final Demo Summary

Date: 2026-06-21

## Positioning

Local Research Agent is a local, inspectable research-paper assistant for importing PDFs, building structured RAG evidence, generating Obsidian reading notes, and answering paper or note questions with a visible execution trail.

## System Architecture

The current demo uses a single-page UI backed by a Harness runtime and a LangGraph-style two-agent flow.

```text
Single-page Vue UI
-> FastAPI boundary
-> Harness runtime
-> LangGraph-style orchestration
-> Knowledge RAG Agent
-> Note Skill Agent
-> ToolGateway
-> File / Database / RAG / Skills tool wrappers
-> SQLite + Chroma or local keyword fallback
-> Obsidian Markdown note output
-> execution payload back to the frontend
```

Key parts:

- Single-page UI: upload, chat, paper list, chat sessions, and execution panel stay in the current app surface.
- Harness: creates task/run/session records, persists execution payloads, and records fallbacks.
- LangGraph-style flow: routes upload, retrieval, note generation, and answering phases.
- Knowledge RAG Agent: handles PDF ingest, parsing, chunking, indexing, and retrieval.
- Note Skill Agent: consumes evidence and generates Obsidian-compatible notes.
- ToolGateway: records MCP-style tool calls, policy decisions, latency, status, and errors.
- RAG: uses layout-aware chunks, sections, tables, figures, note chunks, and retrieval metadata.
- Obsidian note: writes generated Markdown under the configured local Obsidian vault.

## Current Demo Data

| paper_id | title | language | parse_status | vector_status | note_status |
|---|---|---|---|---|---|
| `paper_e2e2a2580ff54f40` | SSVEP 赛题-窄带随机编码 | zh | done | done | partial |
| `paper_64f99d33a5e5438f` | Human-centred physical neuromorphics with visual brain-computer interfaces | en | done | done | done |

Evidence binding is present for both papers:

- Chinese paper: 17 paper chunks, 17 document chunks, 4 image assets, 7 note chunks.
- English paper: 113 paper chunks, 113 document chunks, 5 image assets, 6 note chunks.

The generated Obsidian notes are:

- `C:\Users\liunian\Documents\Agent\obsidian_vault\02_ReadingNotes\SSVEP_赛题-窄带随机编码.md`
- `C:\Users\liunian\Documents\Agent\obsidian_vault\02_ReadingNotes\Human-centred_physical_neuromorphics_with_visual_brain-computer_interfaces.md`

## RAG Evaluation Results

Eval file: `backend/eval/rag_eval_set.local.jsonl`.

Run command:

```powershell
python backend\eval\rag_eval.py --eval-file backend\eval\rag_eval_set.local.jsonl --top-k 10
```

Results:

- Runnable cases: 12
- Skipped cases: 0
- Recall@3: 0.8206
- Recall@5: 0.8444
- MRR: 0.9167
- Evidence Hit Rate: 1.0

The full per-case report is preserved in `docs/rag_eval_report.md`.

## Demo Acceptance Results

All four QA scopes were exercised against the real local library and returned HTTP 200:

| scope | result | evidence payload |
|---|---|---|
| `paper_only` | pass | `rag_evidence`, `harness_decisions`, and `mcp_tool_calls` present |
| `note_only` | pass | `rag_evidence`, `harness_decisions`, and `mcp_tool_calls` present |
| `paper_and_note` | pass | `rag_evidence`, `harness_decisions`, and `mcp_tool_calls` present |
| `global_library` | pass | `rag_evidence`, `harness_decisions`, and `mcp_tool_calls` present |

The full acceptance record is preserved in `docs/demo_acceptance.md`.

## Fallback Behavior

During demo QA, the external model call failed. The system still returned HTTP 200 by using the grouped-evidence fallback answer path.

This means:

- Retrieval can still produce useful evidence without a successful live model call.
- `rag_evidence` remains available in the execution payload.
- Harness fallback decisions remain inspectable.
- The demo does not depend on a single LLM call being available for the request to complete.

This fallback is a resilience behavior, not a replacement for a healthy configured model provider.

## Current Limits

- Folder creation/deletion remains disabled and was not restored for this demo.
- The UI remains a single-page app; no new dashboard or trace page was added.
- Word export is not implemented.
- The Chinese note is intentionally marked `partial` because the available evidence was incomplete for a full note.
- Chroma may fall back to local keyword retrieval when vector dependencies are unavailable.
- MCP-style behavior is currently implemented through in-process Python wrappers plus ToolGateway records, not independent MCP service processes.
- External model availability can affect answer fluency, but not the existence of retrievable evidence or execution payloads.

## Demo Steps

1. Start the backend.

   ```powershell
   cd C:\Users\liunian\Documents\Agent\backend
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

2. Start the frontend.

   ```powershell
   cd C:\Users\liunian\Documents\Agent\frontend
   npm run dev
   ```

3. Open `http://127.0.0.1:5173`.

4. Confirm both SSVEP papers are visible in the library.

5. Select each paper and confirm parse/vector/note status:

   - Chinese paper: parse done, vector done, note partial.
   - English paper: parse done, vector done, note done.

6. Ask a `paper_only` question about the Chinese paper's narrowband random coding stimulus.

7. Ask a `note_only` question about the Chinese note's limitations.

8. Ask a `paper_and_note` question about the English paper's high-density frequency division multiplexing.

9. Ask a `global_library` comparison question across both SSVEP papers.

10. Expand the execution panel under an assistant answer and confirm:

    - Harness decisions are present.
    - RAG evidence is present.
    - MCP tool calls are present.
    - Fallbacks are visible when used.

11. Run the preserved RAG eval command and compare the metrics with `docs/rag_eval_report.md`.

12. For final verification, run:

    ```powershell
    python -m pytest backend\tests -q
    cd C:\Users\liunian\Documents\Agent\frontend
    npm run build
    ```
