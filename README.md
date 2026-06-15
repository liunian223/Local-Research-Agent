# Local Research Agent

Local Research Agent is a local research-paper assistant. It provides a small paper library, PDF upload, local RAG question answering, Obsidian-compatible note generation, chat sessions, and an inspectable execution panel.

The project is already more than a plain PDF QA demo: it has LangGraph-style agent orchestration, Adaptive Layout-Aware RAG v2, a Note Skill Agent flow, ToolGateway/MCP call records, execution payloads, and persisted chat sessions. The P0 handoff is complete: upload and chat endpoints now enter through `backend/harness/runtime.py`, execution payload building and persistence live under `backend/harness/execution_builder.py`, chat history restores saved assistant execution payloads from `agent_tasks.execution_json`, and deleting a paper cleans paper/note vector records before database rows are removed. The P1 boundary pass is complete as well: Database MCP now exposes named paper/chunk/delete tools, key upload/note/delete database writes use those named wrappers, and trace/MCP/A2A logs share the same redaction helper. The P2 frontend pass is complete: execution payloads now have typed frontend contracts, the execution panel shows readable structured summaries before raw JSON details, and the main chat UI text has been cleaned up. The deeper graph handlers still live in `backend/app.py`, so the next optimization is moving more business orchestration behind Harness.

## Current Core Capabilities

- PDF upload with filename, extension, size, header, and path safety checks.
- SQLite-backed paper, chunk, note, task, trace, A2A, MCP, and chat-session storage.
- Adaptive Layout-Aware RAG v2 with page, section, block, table, figure, semantic chunk, abstract, and retrieval metadata.
- Chroma vector retrieval by default, with local keyword fallback when Chroma or embedding dependencies are unavailable.
- Structured retrieval modes for simple rerank, complex planned retrieval, table lookup, figure lookup, page lookup, and global library search.
- Note Skill Agent v1.4 for evidence-based Obsidian Markdown note generation, note quality checks, repair attempts, note chunks, and note vector indexing.
- LangGraph-style two-agent flow with `Knowledge RAG Agent` and `Note Skill Agent` nodes.
- ToolGateway records MCP-style tool calls, policy decisions, summaries, latency, status, and errors.
- Database MCP exposes named paper, chunk, note, status, and delete-artifact operations used by the main upload/note/delete paths.
- Trace, MCP, and A2A logs use shared redaction for API keys, uploaded bytes, full paper text, and note markdown.
- Frontend execution panel uses typed execution payload contracts and displays graph nodes, MCP calls, A2A messages, Harness summary, RAG metadata, evidence bundles, note generation details, and fallbacks.
- Chat sessions are persisted and can be created, selected, deleted, and restored after refresh, including saved assistant execution payloads.
- Paper deletion removes database rows and local artifacts, and it invokes vector cleanup for paper and note records.

## Current Real Structure

```text
backend/
  app.py
  adaptive_rag/
  agents/
  graph/
  harness/
  llm/
  mcp_client/
  mcp_servers/
  tests/
  note_skill.py
  chat_sessions.py
  database.py
  schema.sql
  tool_gateway.py
  layout_parser.py
  semantic_chunker.py
  structured_retriever.py
  vector_store.py
frontend/
  src/
    components/ExecutionPanel.vue
    views/MainChatView.vue
    App.vue
    main.ts
    styles.css
    types.ts
docs/
  project_structure_evaluation.md
  development_roadmap.md
  python_file_consolidation_audit.md
data/
obsidian_vault/
```

Important path notes:

- Adaptive RAG code is currently under `backend/adaptive_rag/`, plus `backend/layout_parser.py`, `backend/semantic_chunker.py`, and `backend/structured_retriever.py`.
- Graph routing, standard flow summaries, and node visit validation live in `backend/graph/builder.py`; the old `backend/graph_runtime.py` wrapper has been removed.
- The Note Skill implementation is currently `backend/note_skill.py`.
- Chat session and history persistence live in `backend/chat_sessions.py`.
- Database code is currently `backend/database.py` and `backend/schema.sql`.
- `ToolGateway` is currently implemented in `backend/tool_gateway.py`.
- MCP tools are currently in-process Python wrappers under `backend/mcp_servers/`; they are not independent MCP service processes.
- `backend/rag/`, `backend/skills/`, and `backend/database/` are not current real directories.
- `frontend/src/api/` and `frontend/src/stores/` are not current real directories; API calls and state are mostly inside `frontend/src/views/MainChatView.vue`.

## Architecture

```text
Frontend
-> FastAPI backend/app.py
   -> Harness Runtime backend/harness/runtime.py
      -> task/session/run initialization
      -> upload/chat graph runner callbacks
   -> LangGraph-style flow
      -> Knowledge RAG Agent
         -> PDF parsing, layout artifacts, chunks, retrieval
      -> Note Skill Agent
         -> evidence consumption, note generation, note indexing, chat answers
   -> ToolGateway at backend/tool_gateway.py
      -> in-process File / Database / RAG / Skills MCP wrappers
   -> SQLite, Chroma/local keyword fallback, Obsidian vault
-> execution payload for frontend display
```

Current boundary:

- LangGraph handles task phases, routing, node visit guards, and two-agent coordination.
- `backend/harness/runtime.py` is now the upload/chat task entrypoint used by the API endpoints.
- `backend/harness/execution_builder.py` now owns full execution payload construction and `agent_tasks.execution_json` persistence.
- `backend/chat_sessions.py` now owns chat session listing, creation, deletion, history loading, and historical execution restore.
- `backend/app.py` still owns FastAPI validation plus the graph runner callbacks and several business handlers.
- `backend/harness/` contains useful policy, context, security, fallback, and execution-builder helpers.
- `backend/mcp_servers/database_mcp_server.py` now contains named `insert_paper`, `insert_chunks`, `insert_note`, `insert_note_chunks`, `update_paper_status`, and `delete_paper_artifacts` helpers.
- `backend/database.py` applies shared redaction to trace, MCP, and A2A log records.
- The next Harness optimization is moving more graph handlers and business orchestration out of `app.py` so the API layer becomes thinner.
- ToolGateway is the current tool-call boundary for key MCP-style file, database, RAG, skill, and model operations.

## Adaptive Layout-Aware RAG v2

Upload and retrieval use structured paper artifacts rather than only fixed-size text chunks.

Upload flow:

```text
PDF upload
-> text parsing fallback chain
-> layout parsing with PyMuPDF blocks
-> page/header/footer metadata
-> section detection
-> abstract detection and isolation
-> table and figure metadata from captions/nearby text
-> semantic chunks with context_prefix and source metadata
-> SQLite persistence
-> Chroma indexing, or local keyword fallback
```

Parsed artifacts live under `data/parsed/{paper_id}/` and include pages, sections, blocks, chunks, tables, figures, metadata, and summaries. SQLite stores parallel structure in `document_pages`, `document_sections`, `document_blocks`, `document_tables`, `document_figures`, `document_chunks`, `chunk_links`, and compatibility rows in `paper_chunks`.

The RAG path supports:

- `simple_retrieve_rerank`
- `complex_planned_retrieval`
- `simple_vector` as a legacy-compatible mode name
- `complex_section_expansion` as a legacy-compatible mode name
- `table_lookup`
- `figure_lookup`
- `page_lookup`
- `global_structured_retrieval`

Execution payloads include `execution.rag_pipeline`, `execution.retrieval`, `execution.evidence_bundle`, and `execution.rag_evidence`.

## Note Skill Agent v1.4

The Note Skill Agent consumes structured evidence and generates Obsidian-compatible notes. The implementation currently lives in `backend/note_skill.py`, with orchestration still mostly in `backend/app.py`.

The note flow can:

- Prefer `evidence_bundle` from Adaptive RAG.
- Fall back to flat `retrieved_chunks` or safe parsed text when needed.
- Distinguish abstract clues from body evidence.
- Generate Markdown with YAML frontmatter and structured sections.
- Run quality checks and limited repairs.
- Write Markdown to the Obsidian note directory.
- Copy the source PDF to the Obsidian attachment directory.
- Save `reading_notes` and `note_chunks`.
- Build a note vector index for `note_only` and `paper_and_note` retrieval.

Execution payloads include `execution.note_generation` and `execution.skill_phases`.

## Harness And ToolGateway

Harness-related files currently exist under `backend/harness/`:

- `policy.py`
- `context_manager.py`
- `execution_builder.py`
- `security.py`
- `fallback_manager.py`
- `runtime.py`

`backend/harness/runtime.py` is now the first upload/chat runtime controller. It provides `run_upload_task()` and `run_chat_task()`, and the FastAPI upload/chat endpoints call those functions instead of creating task/session/run records directly.

The current Runtime responsibilities are:

- Create task and run IDs.
- Resolve and touch chat sessions.
- Persist task rows before execution.
- Invoke the upload/chat graph runner callbacks.
- Collect evidence, skill phases, fallbacks, retrieval metadata, and note generation metadata from the final graph state.
- Build and save the execution payload through `backend/harness/execution_builder.py`.
- Return API-ready response objects.

The next major architecture step is to move more of the graph and business orchestration behind Harness Runtime so that:

- `backend/app.py` only handles FastAPI request validation and response return.
- Harness owns more LangGraph invocation details directly.
- Tool calls consistently go through `backend/tool_gateway.py`.
- traces, MCP calls, A2A messages, fallbacks, redaction, and execution payloads are built consistently.

The P1 boundary pass adds:

- Database MCP named tools for `insert_paper`, `insert_chunks`, `delete_paper_artifacts`, note insertion, note chunk insertion, and paper note-status updates.
- Upload ingestion uses Database MCP for paper rows and structured chunk/artifact rows.
- Note generation uses File MCP wrappers and Database MCP wrappers for note files, copied attachments, note rows, note chunks, and paper status updates.
- Paper deletion uses `delete_paper_artifacts()` for database cleanup after vector cleanup and local artifact removal.
- Trace, MCP, and A2A records share `harness.context_manager.redact_value()` for redaction.

MCP is currently implemented as in-process Python wrappers, not standalone service processes. This is intentional for the local demo, and any future independent MCP server process should be treated as a separate architecture change.

## Chat Sessions

Sessions scope chat history and restored UI context. They do not partition the paper library or the RAG corpus.

Available chat scopes:

- `paper_only`
- `note_only`
- `paper_and_note`
- `global_library`

Endpoints include:

- `GET /api/chat/sessions`
- `POST /api/chat/sessions`
- `DELETE /api/chat/sessions/{session_id}`
- `GET /api/chat/history?session_id=...`
- `POST /api/chat/upload`
- `POST /api/chat/message`

Historical assistant messages include parsed `agent_tasks.execution_json` when a saved execution payload is available. Invalid execution JSON is ignored, so broken historical payloads do not break chat history loading. This lets the frontend restore `message.execution` and keep the execution panel available after refresh.

## Paper Deletion And Vector Cleanup

`DELETE /api/papers/{paper_id}` removes the paper, related chunks, layout tables, figures, notes, note chunks, local PDF artifacts, and Obsidian note/attachment artifacts. Before deleting the database rows, it calls:

- `VECTOR_STORE.delete_by_paper_id(paper_id)` for paper vectors.
- `VECTOR_STORE.delete_by_note_id(note_id)` for each generated reading note.

The response includes a `vector_cleanup` list with per-target status. If the vector backend is unavailable or the app is running on local keyword fallback, cleanup is reported as a no-op/fallback result because retrieval reads the remaining SQLite rows; those rows are still deleted. Vector cleanup failures are reported but do not block paper deletion.

## Configure Model Providers

OpenAI can be used for chat answers, note generation, JSON-style model tasks, optional vision, and optional embeddings. API keys must stay on the backend side and must not be put in frontend code, execution payloads, traces, or committed files.

PowerShell example:

```powershell
$env:OPENAI_API_KEY="your_api_key"
$env:TEXT_MODEL_PROVIDER="openai"
$env:VISION_MODEL_PROVIDER="openai"
$env:EMBEDDING_PROVIDER="local"
```

The local demo can also read ignored values from `backend/.env`. `backend/.env.example` documents supported provider settings.

DeepSeek remains available as an optional fallback provider:

```powershell
$env:DEEPSEEK_API_KEY="your_api_key"
$env:TEXT_MODEL_PROVIDER="deepseek"
$env:DEEPSEEK_MODEL_CHAT="deepseek-chat"
```

Codex CLI can be tested as a local text provider when the machine is already authenticated:

```env
TEXT_MODEL_PROVIDER=codex_cli
CODEX_CLI_COMMAND=codex
CODEX_CLI_TIMEOUT_SECONDS=180
```

## Configure Obsidian

By default, notes are written to `./obsidian_vault/02_ReadingNotes`.

```powershell
$env:OBSIDIAN_VAULT_PATH="D:\Your\ObsidianVault"
$env:OBSIDIAN_NOTE_DIR="02_ReadingNotes"
```

## Start Backend

```powershell
conda activate agent
cd C:\Users\liunian\Documents\Agent\backend
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Startup runs SQLite migrations automatically, including chat sessions, execution persistence, layout/RAG columns, and compatibility columns.

## Start Frontend

```powershell
cd C:\Users\liunian\Documents\Agent\frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Run Tests

Backend tests:

```powershell
conda activate agent
python -m pytest backend\tests -q
```

Focused Adaptive RAG tests:

```powershell
conda activate agent
python -m pytest backend\tests\test_rag_query_analyzer.py backend\tests\test_rag_abstract_detector.py backend\tests\test_rag_complex_retrieval.py backend\tests\test_rag_adaptive_retriever.py backend\tests\test_rag_execution_payload.py -q
```

Focused Note Skill Agent tests:

```powershell
conda activate agent
python -m pytest backend\tests\test_note_skill_agent_evidence_bundle.py backend\tests\test_note_skill_agent_generate_note.py backend\tests\test_note_skill_agent_answer_chat.py backend\tests\test_note_skill_quality_repair.py backend\tests\test_note_skill_note_index.py -q
```

Focused Harness and ToolGateway tests:

```powershell
conda activate agent
python -m pytest backend\tests\test_harness_runtime.py backend\tests\test_harness_policy.py backend\tests\test_tool_gateway.py backend\tests\test_harness_execution_payload.py backend\tests\test_harness_redaction.py -q
```

Frontend build:

```powershell
cd C:\Users\liunian\Documents\Agent\frontend
npm run build
```

## Demo Flow

1. Start the backend and frontend.
2. Create or select a chat session.
3. Upload an English or Chinese PDF.
4. Ask for an Obsidian reading note.
5. Ask paper, note, paper-and-note, or global-library questions.
6. Search papers by title or author.
7. Refresh the page and confirm session context and historical execution panels are restored.
8. Expand execution details under assistant responses.
9. Delete conversations or papers when needed.

## Current Limits

- Folder creation and deletion are disabled in the current UI/API.
- Search only supports title and author fields.
- OCR fallback is disabled by default.
- Word export is not implemented.
- Table and figure extraction is caption/nearby-text based; it does not claim visual understanding.
- MCP is in-process Python wrapper code plus ToolGateway records, not independent service processes.
- Harness Runtime is now the upload/chat task entrypoint and owns execution payload persistence through `backend/harness/execution_builder.py`, but deeper graph handlers and business orchestration still need to move out of `backend/app.py`.
