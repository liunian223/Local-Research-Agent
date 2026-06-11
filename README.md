# Local Research Agent

Local Research Agent is a local research-paper Agent demo. The left side is a minimal personal paper library; the right side is a research chat surface that can upload PDFs, generate Obsidian-compatible Markdown notes, and answer with local RAG evidence.

## Features

- One-page UI with Personal Library and Research Chat.
- Folder creation and deletion for empty non-system folders.
- Paper search by title and author only.
- Secure PDF upload with extension, size, PDF header, filename, and path checks.
- PDF metadata and text parsing fallback chain.
- SQLite storage for folders, papers, chunks, notes, tasks, traces, A2A messages, and MCP tool-call records.
- Chroma is the configured vector backend by default; if Chroma or its embedding path is unavailable, the app falls back to local keyword RAG for `paper_only`, `note_only`, `paper_and_note`, and `global_library`.
- Optional DeepSeek OpenAI-compatible chat client. If `DEEPSEEK_API_KEY` is unset, the app keeps working through local RAG fallback.
- Explicit LangGraph-style phase metadata, standard task flows, and node visit-limit checks in each response execution payload.
- Graph execution is organized under `backend/graph` with `AgentState`, pure routers, node visit guards, and a runner used by upload/chat APIs.
- Agent node entrypoints live under `backend/agents`: `Knowledge RAG Agent` handles import/retrieval, and `Note Skill Agent` handles note generation/chat answers.
- One exposed skill concept: `run_deep_paper_note_skill`, implemented as local Obsidian Markdown note generation.
- Assistant responses include collapsible execution data for LangGraph-style nodes, MCP calls, A2A-style messages, RAG evidence, skill phases, and fallbacks.
- Generated notes are written to the Obsidian note directory, and the source PDF is copied to the Obsidian attachment directory through the File MCP-style gateway.

## Tech Stack

- Backend: Python 3.10+, FastAPI, SQLite, PyMuPDF/pdfplumber/pypdf fallback parsing.
- Frontend: Vue 3, Vite, TypeScript, Axios.
- Storage: `data/local_research_agent.db`, `data/papers`, `data/parsed`, `data/vector_store`, `obsidian_vault/02_ReadingNotes`, `obsidian_vault/attachments/papers`.

## Configure DeepSeek

The first runnable version works offline with local RAG fallback. Do not hard-code API keys. When `DEEPSEEK_API_KEY` is set, chat answers use the DeepSeek OpenAI-compatible API with local RAG evidence:

```powershell
$env:DEEPSEEK_API_KEY="your_api_key"
$env:DEEPSEEK_MODEL_CHAT="deepseek-v4-flash"
$env:DEEPSEEK_MODEL_NOTE="deepseek-v4-pro"
$env:DEEPSEEK_MODEL_JSON="deepseek-v4-pro"
```

You can copy `backend/.env.example` as a local reference, but keep the real key in your shell environment or an ignored `.env` file.

## Set Obsidian Vault Path

By default notes are written to `./obsidian_vault/02_ReadingNotes`. To use your own vault:

```powershell
$env:OBSIDIAN_VAULT_PATH="D:\Your\ObsidianVault"
$env:OBSIDIAN_NOTE_DIR="02_ReadingNotes"
```

## Start Backend

```powershell
conda activate agent
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

## Start Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Run Tests

Backend acceptance tests use isolated temporary data, database, and Obsidian vault paths. Run them from the Anaconda `agent` environment:

```powershell
conda activate agent
python -m pytest backend\tests -q
```

The tests cover health, `All Papers`, folder deletion rules, PDF upload security, note generation, Obsidian attachment copying, graph execution nodes, MCP-style tool calls, and `paper_and_note` retrieval.

## Demo Flow

1. Open the app and confirm `All Papers` appears.
2. Create a folder, for example `GNN`.
3. Upload an English or Chinese PDF.
4. Inspect parse, RAG, and note status in the paper card.
5. Ask for an Obsidian reading note.
6. Ask questions with `paper_only`, `note_only`, `paper_and_note`, or `global_library`.
7. Expand execution details under the assistant response.

## Current Limits

- Folders only support first-level creation and deletion of empty folders.
- Search only supports title and authors.
- OCR fallback is disabled by default.
- Word export is not implemented.
- The first version exposes only one Deep Paper Note Skill.
- MCP runs in-process through ToolGateway records instead of four independent service processes, matching the v1.2 demo deployment note.
- Graph execution uses official LangGraph through `StateGraph`; run the backend with the Anaconda `agent` environment so the installed runtime is actually used.
- RAG attempts Chroma first and uses a local keyword fallback when Chroma or embedding dependencies are unavailable.
- PDF parsing may be `partial` or `failed`, but the paper is still allowed into the local library.
