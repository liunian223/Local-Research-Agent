# Local Research Agent Codex 开发文档 v1.2（评审修订版）

> 适用场景：比赛本地演示 / 本地科研论文知识库 / 双 Agent 协作 / DeepSeek API / Obsidian Markdown 笔记沉淀  
> 原始文档来源：`Local Research Agent Codex 完整开发笔记 v1.1`  
> 修订日期：2026-06-11  
> 结论：原方案方向正确、可实现，但需要在 DeepSeek 模型配置、LangGraph 路由写法、MCP 落地方式、RAG scope、Skill 文件写入职责、数据库索引与安全边界上做修订，才能更适合 Codex 开发和比赛本地演示。

---

## 0. 评审结论

### 0.1 是否能达到开发需求

可以达到比赛演示需求。原文档已经覆盖以下核心能力：

- 单页式科研 Agent UI：左侧个人知识库，右侧 Research Chat。
- 两个 Agent 节点：一个负责知识库/RAG，一个负责阅读、问答和笔记生成。
- 本地 PDF 入库、解析、元数据兜底、正文解析兜底。
- 本地向量索引与 RAG evidence 展示。
- Obsidian-compatible Markdown 阅读笔记生成。
- LangGraph 编排、MCP 工具调用、A2A-style 消息展示、Skill 阶段展示。
- 长论文分阶段生成和 partial note 降级。

但原文档直接交给 Codex 实现时，范围偏大，且存在几处会影响可运行性的模糊点。建议按本文 v1.2 版本实施。

### 0.2 可行性判断

| 维度 | 结论 | 说明 |
|---|---|---|
| 比赛本地演示 | 可行 | 用 FastAPI + Vue + SQLite + Chroma + DeepSeek API 可以完成闭环。 |
| 双 Agent 设计 | 可行 | 建议明确为 `Knowledge RAG Agent` 和 `Note Skill Agent`，不要拆成两个服务。 |
| LangGraph | 可行 | 必须使用明确 phase，路由函数保持纯路由，不在 router 内修改 state。 |
| MCP | 可行但需收敛 | 建议用 FastMCP 本地模块或挂载式 Streamable HTTP，不要首版做四个独立进程。 |
| RAG | 可行 | 建议默认 Chroma，配 metadata filter；不要首版同时支持 Chroma 和 FAISS。 |
| PDF 解析 | 可行但不保证完美 | PyMuPDF + pdfplumber + pypdf 足够演示；OCR 默认关闭。 |
| 长论文笔记 | 可行 | 必须分阶段、按 section 生成，不能一次性塞入模型。 |
| DeepSeek API | 可行但需修改默认模型 | 默认模型从 `deepseek-chat` 改为 `deepseek-v4-flash`，长文/JSON 可用 `deepseek-v4-pro`。 |

### 0.3 必须修改的点

1. **DeepSeek 默认模型需要更新**  
   原文档使用 `deepseek-chat` 作为默认模型。v1.2 改为：
   - `DEEPSEEK_MODEL_CHAT=deepseek-v4-flash`
   - `DEEPSEEK_MODEL_NOTE=deepseek-v4-pro`
   - `DEEPSEEK_MODEL_JSON=deepseek-v4-pro`
   - 仍允许环境变量覆盖。

2. **两个 Agent 命名和职责需要贴合比赛叙事**  
   原文档中的 `Paper Reading Agent Node` 改为 `Note Skill Agent Node` 更清晰：
   - `Knowledge RAG Agent`：论文入库、解析、chunk、embedding、RAG 检索。
   - `Note Skill Agent`：调用 Deep Paper Note Skill 生成笔记，基于 evidence 回答问题。

3. **LangGraph 路由函数不要修改 state**  
   原文档在 `route_after_knowledge` / `route_after_paper_reading` 中直接修改 `state["phase"]`。这会让调试变难。v1.2 要求：节点负责写 state，router 只返回下一个节点名。

4. **`chat_scope` 需要补齐 `paper_and_note`**  
   原文档前端有 `paper_and_note`，但 RAG 章节只列出 `paper_only`、`note_only`、`global_library`。v1.2 明确四种 scope 全部支持。

5. **Skill 不直接写文件**  
   `Deep Paper Note Skill` 只负责生成结构化 Markdown 和质量检查结果；写入 Obsidian Vault 由 File MCP 的 `write_markdown_note` 完成，数据库状态由 Database MCP 更新。这样不会破坏 “Agent 不直接绕过 Harness/MCP 写文件/数据库” 的原则。

6. **MCP 落地方式需要收敛**  
   第一版仍保留四个 MCP Server 的逻辑分组，但运行上建议使用同一个 FastAPI 进程内的 FastMCP server 或 mounted Streamable HTTP，不要比赛首版管理四个独立服务进程。

7. **数据库与向量库需要增加索引和 source metadata**  
   向量索引必须保存 `source_type=paper|note`、`paper_id`、`note_id`、`folder_id`、`section_name`，否则 `paper_only`、`note_only`、`global_library` 很难稳定过滤。

8. **增加 PDF 上传安全边界**  
   必须限制文件类型、文件大小、路径穿越、重复文件、非法文件名。比赛本地演示也不能允许任意路径写入。

### 0.4 首版不建议实现的内容

以下内容保留为 optional，不进入比赛 MVP：

- OCR 兜底默认关闭；可配置但不强依赖。
- 多进程 MCP server 管理器。
- Word 导出。
- 多级文件夹、标签、全文搜索 UI。
- 单独 Trace 页面、MCP 页面、A2A 页面。
- 复杂 PDF 版面恢复和公式/表格结构化解析。
- 后台任务队列；比赛本地演示可同步执行，前端显示 loading。

---

## 1. 项目名称

`Local Research Agent`

---

## 2. 项目定位

Local Research Agent 是一个面向科研论文阅读、个人论文知识库构建和 Obsidian 笔记沉淀的本地科研 Agent 系统。

系统采用单页对话式交互：

- 左侧：Personal Library，展示最简个人论文知识库。
- 右侧：Research Chat，完成 PDF 拖拽上传、自然语言任务、阅读笔记生成和问答。

后端通过 Harness 统一约束执行过程，通过 LangGraph 管理两个 Agent 节点，通过 MCP 调用本地文件、数据库、RAG 和主 Skill，通过 RAG 提供 evidence，通过 A2A-style message 展示两个 Agent 节点之间的协作过程。

本项目不是普通论文摘要工具，也不是简单套一个大模型 API。比赛演示时要突出：

1. 这是本地个人科研知识库。
2. 这是双 Agent 协作系统。
3. 所有工具调用被 Harness 约束。
4. RAG evidence、MCP 调用、LangGraph 路径、A2A-style 消息、Skill 阶段都可以在回答中折叠展示。

---

## 3. MVP 核心目标

第一版必须实现：

1. 本地个人论文知识库。
2. 左侧最简文件夹管理。
3. 支持创建文件夹。
4. 支持删除空文件夹。
5. 支持按论文标题和作者搜索论文。
6. 支持 PDF 拖拽上传和点击上传。
7. 支持中文论文和英文论文导入。
8. 支持 PDF 元数据提取兜底。
9. 支持 PDF 正文解析失败兜底。
10. 支持本地向量索引和 RAG 检索。
11. 支持生成 Obsidian-compatible Markdown 阅读笔记。
12. 支持长论文分阶段生成笔记。
13. 支持当前论文问答。
14. 支持当前笔记问答。
15. 支持当前论文 + 当前笔记问答。
16. 支持全知识库问答。
17. 使用 LangGraph 管理两个 Agent 节点。
18. 使用 MCP 调用本地工具。
19. 第一版只暴露一个主 Skill：`Deep Paper Note Skill`。
20. 在 Assistant 回答中折叠展示 LangGraph、MCP、A2A-style、RAG、Skill、降级策略执行过程。

---

## 4. 不实现内容

第一版不要实现：

- 多页面 Dashboard。
- 单独 Trace 页面。
- 单独 MCP 页面。
- 单独 A2A 页面。
- 单独 RAG Evidence 页面。
- 文件夹拖拽。
- 移动文件夹。
- 多级文件夹。
- 标签系统。
- 全文搜索 UI。
- 复杂右键菜单。
- Word 导出。
- 多个对外 Skill。
- 两个 Agent 作为两个独立服务。
- Agent 绕过 Harness 直接调用数据库、文件系统或 RAG 函数。
- DeepSeek API key 写死在代码里。
- PDF 解析失败导致整个任务崩溃。
- 长论文一次性塞入大模型上下文。
- LangGraph 条件边没有明确 phase。
- router 函数内部修改 state。

---

## 5. 最终产品形态

### 5.1 单页 UI

```text
┌────────────────────────────────────────────────────────────┐
│ Local Research Agent                                      │
├───────────────────────┬────────────────────────────────────┤
│ 左侧：Personal Library │ 右侧：Research Chat                │
│                       │                                    │
│ 搜索论文标题/作者      │ 拖拽 PDF / 点击上传 PDF             │
│ 文件夹列表             │ 输入自然语言任务                    │
│ 当前文件夹论文列表      │ 显示 Assistant 回答                 │
│ 当前选中论文状态        │ 回答下方折叠显示 execution           │
└───────────────────────┴────────────────────────────────────┘
```

### 5.2 左侧 Personal Library

必须包含：

- 搜索框。
- 新建文件夹按钮。
- 文件夹列表。
- 当前文件夹下论文列表。
- 当前选中论文状态。

文件夹限制：

- 只支持一级文件夹。
- 默认存在 `All Papers`。
- `All Papers` 不能删除。
- 删除文件夹时，如果文件夹下存在论文，后端拒绝删除并返回明确错误。
- 不支持文件夹拖拽。
- 不支持移动文件夹。
- 不支持多级目录。

论文搜索只支持：

- `papers.title`
- `papers.authors`

不要搜索：摘要、关键词、标签、笔记正文、全文 chunk、年份。

### 5.3 右侧 Research Chat

必须支持：

- 文本输入。
- PDF 拖拽上传。
- PDF 点击上传。
- 选择问答范围。
- 显示用户消息。
- 显示 Assistant 回答。
- Assistant 回答中折叠展示执行过程。

问答范围：

| 前端显示 | chat_scope |
|---|---|
| 当前论文 + 当前笔记 | `paper_and_note` |
| 当前论文 | `paper_only` |
| 当前笔记 | `note_only` |
| 全知识库 | `global_library` |

默认：`paper_and_note`。

---

## 6. 技术栈

### 6.1 前端

- Vue 3
- Vite
- TypeScript
- Pinia
- Axios
- Element Plus 或 Naive UI
- Markdown 渲染组件

前端只负责展示和交互，不承担 Agent 逻辑。

### 6.2 后端

- Python 3.10+
- FastAPI
- Uvicorn
- Pydantic v2
- SQLAlchemy 2.x
- SQLite
- LangGraph
- MCP Python SDK / FastMCP
- PyMuPDF
- pdfplumber
- pypdf
- ChromaDB，作为第一版默认向量库
- sentence-transformers
- OpenAI Python SDK，用于调用 DeepSeek OpenAI-compatible API

### 6.3 本地存储

- SQLite：文件夹、论文、chunks、笔记、任务、trace、A2A-style、MCP 调用记录。
- Chroma Persistent Directory：论文 chunk 和笔记 chunk 的向量索引。
- Local Files：原始 PDF、解析文本、Obsidian Markdown 输出。

---

## 7. 项目目录结构

```text
local-research-agent/
├─ backend/
│  ├─ app.py
│  ├─ config.py
│  ├─ requirements.txt
│  │
│  ├─ api/
│  │  ├─ chat_api.py
│  │  ├─ paper_api.py
│  │  └─ folder_api.py
│  │
│  ├─ graph/
│  │  ├─ state.py
│  │  ├─ builder.py
│  │  ├─ nodes.py
│  │  └─ checkpoint.py
│  │
│  ├─ harness/
│  │  ├─ runtime.py
│  │  ├─ policy.py
│  │  ├─ context_manager.py
│  │  ├─ tool_gateway.py
│  │  ├─ a2a_gateway.py
│  │  ├─ security.py
│  │  └─ trace_logger.py
│  │
│  ├─ agents/
│  │  ├─ knowledge_rag_agent.py
│  │  └─ note_skill_agent.py
│  │
│  ├─ mcp_client/
│  │  ├─ client_manager.py
│  │  └─ tool_invoker.py
│  │
│  ├─ mcp_servers/
│  │  ├─ file_mcp_server.py
│  │  ├─ database_mcp_server.py
│  │  ├─ rag_mcp_server.py
│  │  └─ skills_mcp_server.py
│  │
│  ├─ skills/
│  │  └─ deep_paper_note_skill.py
│  │
│  ├─ rag/
│  │  ├─ chunker.py
│  │  ├─ embedder.py
│  │  ├─ vector_store.py
│  │  ├─ retriever.py
│  │  └─ note_chunker.py
│  │
│  ├─ database/
│  │  ├─ models.py
│  │  ├─ crud.py
│  │  ├─ init_db.py
│  │  └─ schema.sql
│  │
│  ├─ llm/
│  │  ├─ deepseek_client.py
│  │  └─ prompts.py
│  │
│  └─ utils/
│     ├─ file_utils.py
│     ├─ id_utils.py
│     ├─ lang_utils.py
│     └─ time_utils.py
│
├─ frontend/
│  ├─ package.json
│  ├─ vite.config.ts
│  └─ src/
│     ├─ main.ts
│     ├─ App.vue
│     ├─ views/
│     │  └─ MainChatView.vue
│     ├─ components/
│     │  ├─ KnowledgeSidebar.vue
│     │  ├─ FolderList.vue
│     │  ├─ PaperList.vue
│     │  ├─ PaperCard.vue
│     │  ├─ ChatWindow.vue
│     │  ├─ ChatInput.vue
│     │  ├─ MessageBubble.vue
│     │  └─ ExecutionCollapsePanel.vue
│     ├─ stores/
│     │  ├─ paperStore.ts
│     │  ├─ folderStore.ts
│     │  └─ chatStore.ts
│     └─ api/
│        ├─ chat.ts
│        ├─ papers.ts
│        └─ folders.ts
│
├─ data/
│  ├─ papers/
│  ├─ parsed/
│  └─ vector_store/
│
├─ obsidian_vault/
│  ├─ 02_ReadingNotes/
│  └─ attachments/
│     └─ papers/
│
├─ outputs/
│  └─ traces/
│
├─ docs/
│  ├─ development.md
│  └─ demo_script.md
│
└─ README.md
```

---

## 8. 配置

创建 `backend/config.py`。

```python
import os

PROJECT_NAME = "Local Research Agent"

# DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL_CHAT = os.getenv("DEEPSEEK_MODEL_CHAT", "deepseek-v4-flash")
DEEPSEEK_MODEL_NOTE = os.getenv("DEEPSEEK_MODEL_NOTE", "deepseek-v4-pro")
DEEPSEEK_MODEL_JSON = os.getenv("DEEPSEEK_MODEL_JSON", "deepseek-v4-pro")
DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90"))
DEEPSEEK_MAX_RETRIES = int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))

# Database and storage
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_research_agent.db")
DATA_DIR = os.getenv("DATA_DIR", "../data")
PAPER_DIR = os.getenv("PAPER_DIR", "../data/papers")
PARSED_DIR = os.getenv("PARSED_DIR", "../data/parsed")
VECTOR_DIR = os.getenv("VECTOR_DIR", "../data/vector_store")
OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "../obsidian_vault")
OBSIDIAN_NOTE_DIR = os.getenv("OBSIDIAN_NOTE_DIR", "02_ReadingNotes")
OBSIDIAN_ATTACHMENT_DIR = os.getenv("OBSIDIAN_ATTACHMENT_DIR", "attachments/papers")

# Upload security
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "80"))
ALLOWED_UPLOAD_EXTENSIONS = {".pdf"}

# RAG
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "chroma")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))
CHUNK_SIZE_ZH = int(os.getenv("CHUNK_SIZE_ZH", "900"))
CHUNK_SIZE_EN = int(os.getenv("CHUNK_SIZE_EN", "900"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))

# Long paper handling
LONG_PAPER_CHAR_THRESHOLD = int(os.getenv("LONG_PAPER_CHAR_THRESHOLD", "60000"))
LONG_PAPER_CHUNK_THRESHOLD = int(os.getenv("LONG_PAPER_CHUNK_THRESHOLD", "80"))
LONG_PAPER_PAGE_THRESHOLD = int(os.getenv("LONG_PAPER_PAGE_THRESHOLD", "30"))
MAX_CONTEXT_CHARS_PER_LLM_CALL = int(os.getenv("MAX_CONTEXT_CHARS_PER_LLM_CALL", "16000"))
MAX_EVIDENCE_ITEMS = int(os.getenv("MAX_EVIDENCE_ITEMS", "20"))
MAX_EVIDENCE_CHARS = int(os.getenv("MAX_EVIDENCE_CHARS", "1200"))
MAX_NOTE_REPAIR_ROUNDS = int(os.getenv("MAX_NOTE_REPAIR_ROUNDS", "2"))

# Optional OCR
ENABLE_OCR_FALLBACK = os.getenv("ENABLE_OCR_FALLBACK", "false").lower() == "true"
```

说明：

- 不允许在代码中写死 DeepSeek API key。
- `deepseek-v4-flash` 用于普通问答和轻量任务。
- `deepseek-v4-pro` 用于笔记生成、结构化 JSON、质量修复等较复杂任务。
- 即使 DeepSeek 支持长上下文，也必须保留 RAG 和分阶段生成，避免演示成本和延迟失控。

---

## 9. 数据库设计

使用 SQLite。初始化时开启 WAL：

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

### 9.1 folders

```sql
CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  is_system INTEGER DEFAULT 0,
  created_at TEXT,
  updated_at TEXT
);
```

初始化必须创建：

```text
id = folder_all
name = All Papers
is_system = 1
```

规则：

- `All Papers` 不允许删除。
- 第一版不支持 parent_id。

### 9.2 papers

```sql
CREATE TABLE IF NOT EXISTS papers (
  id TEXT PRIMARY KEY,
  title TEXT,
  authors TEXT,
  year TEXT,
  language TEXT,
  doi TEXT,
  file_path TEXT NOT NULL,
  file_name TEXT,
  file_sha256 TEXT UNIQUE,
  page_count INTEGER DEFAULT 0,
  folder_id TEXT,
  parse_status TEXT DEFAULT 'none',
  vector_status TEXT DEFAULT 'none',
  note_status TEXT DEFAULT 'none',
  obsidian_note_path TEXT,
  metadata_source TEXT,
  metadata_confidence REAL DEFAULT 0.0,
  metadata_warning TEXT,
  parse_warning TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(folder_id) REFERENCES folders(id)
);

CREATE INDEX IF NOT EXISTS idx_papers_folder_id ON papers(folder_id);
CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title);
CREATE INDEX IF NOT EXISTS idx_papers_authors ON papers(authors);
```

状态枚举：

- `parse_status`: `none | done | partial | failed`
- `vector_status`: `none | done | partial | skipped | failed`
- `note_status`: `none | done | partial | failed`

### 9.3 paper_chunks

```sql
CREATE TABLE IF NOT EXISTS paper_chunks (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  section_name TEXT,
  chunk_index INTEGER,
  text TEXT,
  vector_id TEXT,
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper_id ON paper_chunks(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_chunks_section ON paper_chunks(section_name);
```

### 9.4 reading_notes

```sql
CREATE TABLE IF NOT EXISTS reading_notes (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  content_markdown TEXT,
  obsidian_path TEXT,
  quality_check_json TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_reading_notes_paper_id ON reading_notes(paper_id);
```

### 9.5 note_chunks

为了支持 `note_only` 和 `paper_and_note` 检索，必须保存笔记 chunks。

```sql
CREATE TABLE IF NOT EXISTS note_chunks (
  id TEXT PRIMARY KEY,
  note_id TEXT NOT NULL,
  paper_id TEXT NOT NULL,
  section_name TEXT,
  chunk_index INTEGER,
  text TEXT,
  vector_id TEXT,
  created_at TEXT,
  FOREIGN KEY(note_id) REFERENCES reading_notes(id),
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_note_chunks_note_id ON note_chunks(note_id);
CREATE INDEX IF NOT EXISTS idx_note_chunks_paper_id ON note_chunks(paper_id);
```

### 9.6 agent_tasks

```sql
CREATE TABLE IF NOT EXISTS agent_tasks (
  id TEXT PRIMARY KEY,
  task_type TEXT,
  user_input TEXT,
  status TEXT,
  current_paper_id TEXT,
  current_folder_id TEXT,
  chat_scope TEXT,
  answer TEXT,
  created_at TEXT,
  updated_at TEXT
);
```

### 9.7 agent_traces

```sql
CREATE TABLE IF NOT EXISTS agent_traces (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  step_index INTEGER,
  node_name TEXT,
  agent_name TEXT,
  action_type TEXT,
  summary TEXT,
  status TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_traces_task_id ON agent_traces(task_id);
```

### 9.8 a2a_messages

```sql
CREATE TABLE IF NOT EXISTS a2a_messages (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  from_agent TEXT,
  to_agent TEXT,
  message_type TEXT,
  payload TEXT,
  status TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_a2a_task_id ON a2a_messages(task_id);
```

### 9.9 mcp_tool_calls

```sql
CREATE TABLE IF NOT EXISTS mcp_tool_calls (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  server_name TEXT,
  tool_name TEXT,
  input_summary TEXT,
  output_summary TEXT,
  status TEXT,
  error TEXT,
  latency_ms INTEGER,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_task_id ON mcp_tool_calls(task_id);
```

---

## 10. API 设计

所有 API 返回 JSON。错误结构统一：

```json
{
  "error": {
    "code": "folder_not_empty",
    "message": "Cannot delete a non-empty folder."
  }
}
```

### 10.1 Health API

`GET /api/health`

返回：

```json
{
  "status": "ok",
  "project": "Local Research Agent"
}
```

### 10.2 文件夹 API

#### GET /api/folders

返回所有文件夹，`All Papers` 固定第一项。

```json
{
  "folders": [
    {"id": "folder_all", "name": "All Papers", "is_system": true},
    {"id": "folder_gnn", "name": "GNN", "is_system": false}
  ]
}
```

#### POST /api/folders

请求：

```json
{"name": "GNN"}
```

规则：

- 不允许空名称。
- 不允许重复名称。
- 不支持 parent_id。
- 不支持多级文件夹。

#### DELETE /api/folders/{folder_id}

规则：

- `All Papers` 不能删除。
- 非空文件夹不能删除。
- 不需要支持移动论文。

### 10.3 论文 API

#### GET /api/papers?folder_id=xxx

获取某个文件夹下论文。

#### GET /api/papers/search?keyword=xxx

只搜索：

```sql
SELECT * FROM papers
WHERE title LIKE :keyword
   OR authors LIKE :keyword;
```

不要搜索摘要、关键词、全文、笔记、年份。

#### GET /api/papers/{paper_id}

返回论文详情，用于点击 PaperCard 后刷新右侧当前论文状态。

### 10.4 Chat API

#### POST /api/chat/message

请求：

```json
{
  "message": "请为当前论文生成 Obsidian 阅读笔记",
  "current_paper_id": "paper_xxx",
  "current_folder_id": "folder_xxx",
  "chat_scope": "paper_and_note"
}
```

`chat_scope` 允许：

- `paper_and_note`
- `paper_only`
- `note_only`
- `global_library`

返回统一结构：

```json
{
  "task_id": "task_xxx",
  "answer": "已生成 Obsidian Markdown 阅读笔记。",
  "message_type": "note_generated",
  "current_paper": {
    "paper_id": "paper_xxx",
    "title": "..."
  },
  "artifacts": {
    "markdown_path": "obsidian_vault/02_ReadingNotes/xxx.md",
    "pdf_path": "data/papers/xxx.pdf"
  },
  "execution": {
    "langgraph_nodes": [],
    "mcp_tool_calls": [],
    "a2a_messages": [],
    "skill_phases": [],
    "rag_evidence": [],
    "fallbacks": []
  }
}
```

#### POST /api/chat/upload

请求类型：`multipart/form-data`

字段：

- `file`: PDF
- `current_folder_id`: folder id，可为空，空时使用 `folder_all`
- `message`: optional

如果 `message` 为空，默认执行：

```text
导入论文 -> 加入知识库 -> 解析 PDF -> 构建向量索引
```

如果 `message` 包含：

- `生成笔记`
- `阅读笔记`
- `Obsidian`
- `note`

则执行：

```text
导入论文 -> 加入知识库 -> 解析 PDF -> 构建向量索引 -> 生成 Obsidian Markdown 阅读笔记
```

上传安全要求：

- 文件后缀必须为 `.pdf`。
- MIME 类型尽量校验为 PDF。
- 文件大小不得超过 `MAX_UPLOAD_MB`。
- 文件名必须 sanitize，禁止路径穿越。
- 保存时使用 `paper_id` 或 sha256 派生文件名，不直接信任原始文件名。
- 重复 sha256 的 PDF 不重复入库，返回已有 paper。

---

## 11. 前端实现要求

### 11.1 MainChatView.vue

页面只有一个主 view：

```text
left: KnowledgeSidebar
right: ChatWindow
```

不要实现多页面路由。

### 11.2 KnowledgeSidebar.vue

包含：

- 搜索框。
- 新建文件夹按钮。
- 文件夹列表。
- 当前文件夹下论文列表。

交互：

- 点击文件夹后加载该文件夹论文。
- 点击论文后设为 currentPaper。
- 搜索框输入后调用 `/api/papers/search?keyword=xxx`。
- 创建文件夹调用 `POST /api/folders`。
- 删除文件夹调用 `DELETE /api/folders/{folder_id}`。
- 删除非空文件夹时显示后端返回错误。
- 不实现拖拽文件夹。

### 11.3 FolderList.vue

显示：

- `All Papers`
- `GNN`
- `Bitcoin`
- `Agent`

要求：

- `All Papers` 固定在第一项。
- `All Papers` 不显示删除按钮。
- 普通空文件夹可删除。
- 当前选中文件夹高亮。

### 11.4 PaperList.vue / PaperCard.vue

PaperCard 显示：

- 论文标题。
- 作者 / 年份。
- 状态：已解析 / 部分解析 / 解析失败 / 已向量化 / 有笔记。

状态显示规则：

| 字段 | 值 | 显示 |
|---|---|---|
| parse_status | done | 已解析 |
| parse_status | partial | 部分解析 |
| parse_status | failed | 解析失败 |
| vector_status | done | 已向量化 |
| vector_status | partial | 部分向量化 |
| vector_status | skipped | 未向量化 |
| note_status | done | 有笔记 |
| note_status | partial | 部分笔记 |
| note_status | none | 无笔记 |

### 11.5 ChatWindow.vue

包含：

- 当前论文显示。
- 问答范围选择器。
- 消息列表。
- 输入框。
- PDF 拖拽上传区域。

问答范围默认 `paper_and_note`。

### 11.6 ChatInput.vue

支持：

- 输入文本。
- 发送消息。
- 拖拽 PDF。
- 点击上传 PDF。

如果用户未选择文件夹，上传 PDF 时 `current_folder_id` 使用 `folder_all`。

### 11.7 MessageBubble.vue

Assistant 消息显示：

- 回答正文。
- 如果有 `execution`，显示折叠面板。

折叠面板包含：

- LangGraph 执行过程。
- MCP 工具调用。
- A2A-style Agent 通信。
- Deep Paper Note Skill 阶段。
- RAG Evidence。
- 降级 / 兜底提示。

默认折叠。

### 11.8 ExecutionCollapsePanel.vue

示例展示：

```text
LangGraph 执行过程
1. coordinator_node success
2. knowledge_rag_agent_node success
3. note_skill_agent_node success
4. finish_node success

MCP 工具调用
File MCP: save_uploaded_pdf success
Database MCP: insert_paper success
RAG MCP: build_vector_index success
Skills MCP: run_deep_paper_note_skill success
File MCP: write_markdown_note success

A2A-style Agent 通信
Note Skill Agent -> Knowledge RAG Agent: retrieve_evidence
Knowledge RAG Agent -> Note Skill Agent: retrieve_evidence_response

Deep Paper Note Skill 阶段
resolve_input success
normalize_sections success
build_evidence_bundle success
generate_note_plan success
quality_check success

RAG Evidence
Method chunk score=0.86
Experiment chunk score=0.82

降级/兜底提示
metadata_source=filename_or_identifier confidence=0.45
parse_status=partial
```

---

## 12. LangGraph 设计

### 12.1 总体原则

后端必须通过 LangGraph 管理两个 Agent 节点。

不要把两个 Agent 做成两个独立服务。

结构：

```text
LangGraph
├─ coordinator_node
├─ knowledge_rag_agent_node
├─ note_skill_agent_node
└─ finish_node
```

Agent 节点：

- `Knowledge RAG Agent Node`
- `Note Skill Agent Node`

### 12.2 AgentState

`backend/graph/state.py`

```python
from typing import TypedDict, Optional, List, Dict, Any

class AgentState(TypedDict, total=False):
    task_id: str
    user_input: str
    task_type: str

    # LangGraph flow control
    phase: str
    needs_evidence: bool
    evidence_ready: bool
    note_ready: bool
    import_done: bool
    node_visit_count: Dict[str, int]

    # UI context
    current_folder_id: Optional[str]
    current_paper_id: Optional[str]
    current_note_id: Optional[str]
    chat_scope: str

    # File and paper
    uploaded_file_path: Optional[str]
    original_file_name: Optional[str]
    paper_metadata: Dict[str, Any]
    paper_text: str
    page_count: int
    parse_status: str
    parse_warning: str
    metadata_warning: str

    # RAG
    retrieved_chunks: List[Dict[str, Any]]
    rag_evidence: List[Dict[str, Any]]

    # Note generation
    is_long_paper: bool
    section_summaries: Dict[str, Any]
    note_plan: Dict[str, Any]
    partial_note_sections: Dict[str, str]
    note_markdown: Optional[str]
    note_quality_check: Dict[str, Any]
    note_repair_rounds: int

    # Output
    answer: Optional[str]
    artifacts: Dict[str, Any]

    # Execution display
    langgraph_nodes: List[Dict[str, Any]]
    mcp_tool_calls: List[Dict[str, Any]]
    a2a_messages: List[Dict[str, Any]]
    skill_phases: List[Dict[str, Any]]
    fallbacks: List[Dict[str, Any]]

    # Status
    status: str
    error: Optional[str]
```

### 12.3 phase 枚举

```python
PHASES = {
    "START",
    "ROUTE_TASK",
    "IMPORT_PAPER",
    "IMPORT_DONE",
    "REQUEST_EVIDENCE",
    "EVIDENCE_READY",
    "GENERATE_NOTE",
    "NOTE_READY",
    "ANSWER_CHAT",
    "ANSWER_READY",
    "FINISH",
    "ERROR",
}
```

不要在节点中随意创建新 phase。

### 12.4 task_type

允许：

- `import_paper`
- `import_and_note`
- `generate_note`
- `paper_chat`
- `global_chat`

### 12.5 task_type 映射

| 场景 | task_type | 初始 phase |
|---|---|---|
| 上传 PDF，无生成笔记意图 | import_paper | IMPORT_PAPER |
| 上传 PDF，有生成笔记意图 | import_and_note | IMPORT_PAPER |
| 无上传文件，要求生成笔记 | generate_note | REQUEST_EVIDENCE |
| 当前论文/笔记问答 | paper_chat | REQUEST_EVIDENCE |
| 全知识库问答 | global_chat | REQUEST_EVIDENCE |

### 12.6 router 纯路由要求

router 函数只返回下一个节点名，不修改 state。

错误示例，不允许：

```python
def route_after_knowledge(state):
    state["phase"] = "REQUEST_EVIDENCE"  # 不允许在 router 修改 state
    return "knowledge_rag_agent_node"
```

正确方式：

- 节点函数负责更新 `phase`、`needs_evidence`、`evidence_ready`。
- router 只根据已更新的 state 决定下一跳。

### 12.7 条件边设计

```python
def route_after_coordinator(state: AgentState) -> str:
    phase = state.get("phase")
    if phase in {"IMPORT_PAPER", "REQUEST_EVIDENCE"}:
        return "knowledge_rag_agent_node"
    if phase == "ERROR":
        return "finish_node"
    return "finish_node"


def route_after_knowledge(state: AgentState) -> str:
    task_type = state.get("task_type")
    phase = state.get("phase")

    if phase == "ERROR":
        return "finish_node"

    if task_type == "import_paper" and phase == "IMPORT_DONE":
        return "finish_node"

    # import_and_note 的第一次 Knowledge 负责导入；导入完成后，节点内部已经把 phase 设置为 REQUEST_EVIDENCE
    if task_type == "import_and_note" and phase == "REQUEST_EVIDENCE":
        return "knowledge_rag_agent_node"

    if phase == "EVIDENCE_READY":
        return "note_skill_agent_node"

    return "finish_node"


def route_after_note_skill(state: AgentState) -> str:
    phase = state.get("phase")

    if phase == "ERROR":
        return "finish_node"

    if phase == "REQUEST_EVIDENCE":
        return "knowledge_rag_agent_node"

    if phase in {"NOTE_READY", "ANSWER_READY"}:
        return "finish_node"

    return "finish_node"
```

### 12.8 节点访问次数保护

```python
def guard_node_visit(state: AgentState, node_name: str, max_visits: int = 3) -> AgentState:
    counts = state.setdefault("node_visit_count", {})
    counts[node_name] = counts.get(node_name, 0) + 1
    if counts[node_name] > max_visits:
        state["phase"] = "ERROR"
        state["error"] = f"Node {node_name} exceeded max visits."
        state["status"] = "failed"
    return state
```

访问限制：

| node | max_visits |
|---|---:|
| coordinator_node | 1 |
| knowledge_rag_agent_node | 3 |
| note_skill_agent_node | 3 |
| finish_node | 1 |

如果超过访问次数，Assistant 回答：

```text
任务执行中止：检测到异常循环。
```

同时建议 LangGraph invoke 时设置 recursion limit：

```python
graph.invoke(initial_state, config={"recursion_limit": 12})
```

### 12.9 标准流程

#### import_paper

```text
START
→ coordinator_node
  task_type=import_paper
  phase=IMPORT_PAPER
→ knowledge_rag_agent_node
  handle_import_paper()
  import_done=True
  phase=IMPORT_DONE
→ finish_node
→ END
```

#### import_and_note

```text
START
→ coordinator_node
  task_type=import_and_note
  phase=IMPORT_PAPER
→ knowledge_rag_agent_node
  handle_import_paper()
  import_done=True
  phase=REQUEST_EVIDENCE
  needs_evidence=True
→ knowledge_rag_agent_node
  handle_retrieve_evidence()
  evidence_ready=True
  needs_evidence=False
  phase=EVIDENCE_READY
→ note_skill_agent_node
  handle_generate_note()
  note_ready=True
  phase=NOTE_READY
→ finish_node
→ END
```

#### generate_note

```text
START
→ coordinator_node
  task_type=generate_note
  phase=REQUEST_EVIDENCE
  needs_evidence=True
→ knowledge_rag_agent_node
  handle_retrieve_evidence()
  evidence_ready=True
  phase=EVIDENCE_READY
→ note_skill_agent_node
  handle_generate_note()
  note_ready=True
  phase=NOTE_READY
→ finish_node
→ END
```

#### paper_chat

```text
START
→ coordinator_node
  task_type=paper_chat
  phase=REQUEST_EVIDENCE
  needs_evidence=True
→ knowledge_rag_agent_node
  handle_retrieve_evidence()
  evidence_ready=True
  phase=EVIDENCE_READY
→ note_skill_agent_node
  handle_answer_chat()
  phase=ANSWER_READY
→ finish_node
→ END
```

#### global_chat

```text
START
→ coordinator_node
  task_type=global_chat
  phase=REQUEST_EVIDENCE
  needs_evidence=True
→ knowledge_rag_agent_node
  handle_retrieve_evidence(scope=global_library)
  evidence_ready=True
  phase=EVIDENCE_READY
→ note_skill_agent_node
  handle_answer_chat()
  phase=ANSWER_READY
→ finish_node
→ END
```

---

## 13. 两个 Agent 节点职责

### 13.1 Knowledge RAG Agent Node

文件：`backend/agents/knowledge_rag_agent.py`

负责：

1. 保存 PDF。
2. 解析 PDF。
3. 检测中文/英文。
4. 提取 title、authors、year、doi。
5. 将论文写入当前选中文件夹。
6. 切分 chunk。
7. 建立向量索引。
8. 检索 evidence。
9. 搜索论文。
10. 返回 evidence。

不得负责：

- 不生成最终阅读笔记。
- 不直接回答用户长问题。
- 不调用 DeepSeek 做最终回答。
- 不调用 Deep Paper Note Skill。

入口：

```python
def knowledge_rag_agent_node(state: AgentState) -> AgentState:
    phase = state.get("phase")
    if phase == "IMPORT_PAPER":
        return handle_import_paper(state)
    if phase == "REQUEST_EVIDENCE":
        return handle_retrieve_evidence(state)
    state["phase"] = "ERROR"
    state["error"] = f"Knowledge RAG Agent received unsupported phase: {phase}"
    return state
```

#### handle_import_paper

职责：

- File MCP: `save_uploaded_pdf`
- File MCP: `read_pdf_text`
- Database MCP: `insert_paper`
- RAG MCP: `build_vector_index`
- Database MCP: `insert_chunks`

成功：

```python
state["import_done"] = True
state["phase"] = "IMPORT_DONE"
state["status"] = "running"
```

如果 task_type 是 `import_and_note`，导入完成后节点内部直接设置：

```python
state["import_done"] = True
state["phase"] = "REQUEST_EVIDENCE"
state["needs_evidence"] = True
state["status"] = "running"
```

如果解析失败但元数据可用：

```python
state["import_done"] = True
state["parse_status"] = "failed"
state["vector_status"] = "skipped"
state["status"] = "partial"
```

不要直接 ERROR，除非文件保存失败、非法 PDF、数据库写入失败。

#### handle_retrieve_evidence

职责：

- 读取 `chat_scope`。
- 构造 A2A-style `retrieve_evidence` 消息。
- 调用 RAG MCP Server。
- 返回 evidence。
- 设置 `evidence_ready=True`。

成功：

```python
state["retrieved_chunks"] = chunks
state["rag_evidence"] = chunks
state["evidence_ready"] = True
state["needs_evidence"] = False
state["phase"] = "EVIDENCE_READY"
```

如果无 evidence：

```python
state["retrieved_chunks"] = []
state["rag_evidence"] = []
state["evidence_ready"] = True
state["needs_evidence"] = False
state["phase"] = "EVIDENCE_READY"
state.setdefault("fallbacks", []).append({
    "type": "no_evidence",
    "message": "No relevant evidence found."
})
```

不要因为 evidence 为空直接 ERROR。

### 13.2 Note Skill Agent Node

文件：`backend/agents/note_skill_agent.py`

负责：

1. 理解用户阅读/问答任务。
2. 判断是否需要 evidence。
3. 通过 A2A-style 消息向 Knowledge RAG Agent 请求 evidence。
4. 调用 Deep Paper Note Skill。
5. 调用 DeepSeek API 生成问答回答。
6. 整理最终回答。
7. 将 Skill 产物交给 File MCP 写入 Obsidian Markdown。
8. 将笔记状态交给 Database MCP 更新。

不得负责：

- 不直接写 `papers` 表。
- 不直接保存上传 PDF。
- 不绕过 Knowledge RAG Agent 检索 evidence。
- 不直接调用底层 RAG 函数。
- 不直接调用底层文件写入函数。

入口：

```python
def note_skill_agent_node(state: AgentState) -> AgentState:
    task_type = state.get("task_type")
    phase = state.get("phase")

    if phase == "EVIDENCE_READY" and task_type in ["generate_note", "import_and_note"]:
        return handle_generate_note(state)

    if phase == "EVIDENCE_READY" and task_type in ["paper_chat", "global_chat"]:
        return handle_answer_chat(state)

    if phase == "REQUEST_EVIDENCE":
        state["needs_evidence"] = True
        return state

    state["phase"] = "ERROR"
    state["error"] = f"Note Skill Agent received unsupported phase: {phase}"
    return state
```

#### handle_generate_note

职责：

- 检查 evidence 是否已准备好。
- 判断是否长论文。
- Skills MCP: `run_deep_paper_note_skill`
- File MCP: `write_markdown_note`
- File MCP: `copy_pdf_to_obsidian`
- Database MCP: `insert_note`
- Database MCP: 更新 `papers.note_status` 和 `papers.obsidian_note_path`
- RAG MCP: 构建 note chunks 向量索引。
- 设置 `note_ready=True`。

成功：

```python
state["note_ready"] = True
state["phase"] = "NOTE_READY"
state["answer"] = "已生成 Obsidian Markdown 阅读笔记。"
```

部分成功：

```python
state["note_ready"] = True
state["phase"] = "NOTE_READY"
state["status"] = "partial"
state["answer"] = "已生成降级版 Obsidian 阅读笔记，部分章节可能需要人工补充。"
```

失败：

```python
state["phase"] = "ERROR"
state["error"] = "Failed to generate note."
```

#### handle_answer_chat

职责：

- 读取 `retrieved_chunks`。
- 读取 `chat_scope`。
- 构造回答 prompt。
- 调用 DeepSeek。
- 返回 answer。
- 设置 `phase=ANSWER_READY`。

即使 evidence 为空，也要给出回答，但必须说明：

```text
当前知识库中没有检索到足够证据，以下回答基于已有上下文，可靠性较低。
```

成功：

```python
state["phase"] = "ANSWER_READY"
state["answer"] = answer
```

---

## 14. A2A-style Message 设计

内部实现即可，不需要接入外部 A2A 服务。

文件：`backend/harness/a2a_gateway.py`

消息结构：

```python
from pydantic import BaseModel

class A2AMessage(BaseModel):
    id: str
    task_id: str
    from_agent: str
    to_agent: str
    message_type: str
    payload: dict
    status: str = "created"
    created_at: str
```

常用 `message_type`：

- `retrieve_evidence`
- `retrieve_evidence_response`
- `note_generation_request`
- `note_generation_result`

示例：

```json
{
  "from_agent": "note_skill_agent",
  "to_agent": "knowledge_rag_agent",
  "message_type": "retrieve_evidence",
  "payload": {
    "scope": "paper_only",
    "paper_id": "paper_001",
    "query": "方法部分怎么理解",
    "top_k": 8
  }
}
```

A2A-style 消息必须写入：

- `a2a_messages` 表。
- `state.a2a_messages`。

前端在 Assistant 消息中折叠展示。

---

## 15. MCP 设计

必须使用 MCP。不要让 Agent 直接调用普通 Python CRUD、文件写入或 RAG 函数。

第一版逻辑上实现四个 MCP Server，但部署上建议同进程运行：

- 本地 demo 默认：FastMCP + in-process client / mounted Streamable HTTP。
- 不要首版启动四个独立 terminal 进程。
- 所有调用统一经过 `ToolGateway`，统一做 policy 检查、trace 记录、错误包装。

### 15.1 File MCP Server

文件：`backend/mcp_servers/file_mcp_server.py`

Tools：

- `save_uploaded_pdf`
- `read_pdf_text`
- `write_markdown_note`
- `copy_pdf_to_obsidian`
- `read_markdown_note`

### 15.2 Database MCP Server

文件：`backend/mcp_servers/database_mcp_server.py`

Tools：

- `create_folder`
- `delete_folder`
- `list_folders`
- `insert_paper`
- `update_paper_status`
- `list_papers_by_folder`
- `search_papers_by_title_author`
- `insert_chunks`
- `insert_note`
- `insert_note_chunks`
- `insert_trace`
- `insert_a2a_message`
- `insert_mcp_tool_call`

### 15.3 RAG MCP Server

文件：`backend/mcp_servers/rag_mcp_server.py`

Tools：

- `build_vector_index`
- `build_note_vector_index`
- `retrieve_chunks`
- `retrieve_note_blocks`
- `retrieve_paper_and_note`
- `retrieve_global_knowledge`

### 15.4 Skills MCP Server

文件：`backend/mcp_servers/skills_mcp_server.py`

只暴露一个主工具：

- `run_deep_paper_note_skill`

不要暴露：

- `parse_pdf`
- `detect_language`
- `split_chunks`
- `generate_method_section`
- 其他小 skill。

内部阶段可以拆函数，但 MCP 只暴露一个主工具。

### 15.5 MCP Client

文件：

- `backend/mcp_client/client_manager.py`
- `backend/mcp_client/tool_invoker.py`

要求：

- Harness 通过 MCP Client 调工具。
- 所有 MCP 调用记录到 `mcp_tool_calls` 表。
- 所有 MCP 调用加入 `state.mcp_tool_calls`。
- Agent 不允许直接调用数据库 CRUD、RAG 函数、文件写入函数。
- Tool 调用失败时返回结构化错误，不抛出未捕获异常导致任务崩溃。

---

## 16. Harness 设计

Harness 是系统执行控制层。

### 16.1 runtime.py

文件：`backend/harness/runtime.py`

职责：

1. 接收 API 层任务。
2. 创建 `task_id`。
3. 初始化 `AgentState`。
4. 调用 LangGraph。
5. 统一记录 trace。
6. 统一整理 execution 信息。
7. 返回结构化响应。

### 16.2 policy.py

文件：`backend/harness/policy.py`

职责：限制 Agent 可调用工具。

规则：

| Agent | 可调用 |
|---|---|
| Knowledge RAG Agent | File MCP、Database MCP、RAG MCP |
| Note Skill Agent | A2A Gateway、Skills MCP、File MCP 写笔记、Database MCP 更新 note、RAG MCP 构建 note index、DeepSeekClient |

禁止：

- Note Skill Agent 直接写 `papers` 表。
- Note Skill Agent 绕过 Knowledge RAG Agent 检索 paper evidence。
- Knowledge RAG Agent 生成最终阅读笔记。
- Knowledge RAG Agent 调用 Skills MCP。

### 16.3 trace_logger.py

每个节点执行记录：

- `task_id`
- `node_name`
- `agent_name`
- `action_type`
- `summary`
- `status`
- `created_at`

### 16.4 security.py

负责：

- 文件大小检查。
- PDF 后缀和 MIME 检查。
- 文件名 sanitize。
- 路径穿越检查。
- sha256 计算。
- Obsidian 文件名非法字符清理。

---

## 17. PDF 元数据提取兜底方案

### 17.1 元数据字段

```python
paper_metadata = {
    "title": "",
    "authors": "",
    "year": "",
    "language": "",
    "doi": "",
    "metadata_source": "",
    "metadata_confidence": 0.0,
    "metadata_warning": "",
}
```

### 17.2 元数据提取优先级

#### Level 1：PDF 内置 metadata

优先使用 PyMuPDF：

```python
import fitz

doc = fitz.open(pdf_path)
meta = doc.metadata
```

读取：

- `title`
- `author`
- `creationDate`
- `modDate`

接受条件：

- title 非空。
- title 长度大于 5。
- title 不等于文件名乱码。
- title 不包含大量不可见字符。

成功时：

```python
metadata_source = "pdf_metadata"
metadata_confidence = 0.9
```

#### Level 2：首页文本启发式提取

解析前 1-2 页文本，通过启发式提取。

标题候选规则：

1. 优先选择第一页上方较长文本块。
2. 排除 Abstract、摘要、Introduction、引言、关键词等章节标题。
3. 排除邮箱、URL、DOI、页眉页脚。
4. 英文标题通常长度 8-30 个词。
5. 中文标题通常长度 8-50 个中文字符。

作者候选规则：

1. 标题下方 1-5 行内查找作者。
2. 排除单位、邮箱、摘要、关键词。
3. 英文作者一般包含逗号、and、首字母缩写。
4. 中文作者一般为 2-4 个汉字姓名，多个作者之间可能用逗号、顿号、空格分隔。

年份候选规则：

1. 正则匹配 `19xx` 或 `20xx`。
2. 优先从首页、页眉、会议/期刊信息中提取。
3. 如果出现多个年份，优先选择最接近标题或会议信息的年份。

成功时：

```python
metadata_source = "first_page_heuristic"
metadata_confidence = 0.65
```

#### Level 3：DOI / arXiv / 文件名辅助提取

尝试：

1. 从全文前 3 页正则提取 DOI。
2. 从文件名中提取标题候选。
3. 从文件名中提取年份候选。
4. 如果文件名类似 `2025_Zhang_xxx.pdf`，提取 year 和 first_author。

文件名清理规则：

1. 去掉 `.pdf`。
2. 下划线、短横线替换为空格。
3. 去掉 arxiv 编号、版本号、下载编号。
4. 去掉过长随机字符串。

成功时：

```python
metadata_source = "filename_or_identifier"
metadata_confidence = 0.45
```

#### Level 4：LLM 辅助提取

如果 Level 1-3 失败，但 PDF 前几页文本可用，则调用 DeepSeek JSON 模式，从前 2 页文本中提取结构化元数据。

Prompt 要求：

```text
请只输出 json。不要编造不存在的信息。无法判断的字段返回空字符串。
```

目标 JSON：

```json
{
  "title": "",
  "authors": "",
  "year": "",
  "language": "",
  "doi": ""
}
```

成功时：

```python
metadata_source = "llm_first_pages"
metadata_confidence = 0.55
```

#### Level 5：最低兜底

如果所有方法都失败：

```python
title = cleaned_filename
authors = "Unknown"
year = "Unknown"
language = detected_language or "unknown"
doi = ""
metadata_source = "fallback_filename"
metadata_confidence = 0.2
metadata_warning = "Failed to extract reliable metadata. Used filename as title."
```

此时仍允许论文入库，但 Assistant 必须提示：

```text
论文已加入知识库，但元数据提取不完整，标题/作者可能需要人工修改。
```

---

## 18. PDF 正文解析失败兜底方案

### 18.1 解析器优先级

按顺序尝试：

1. PyMuPDF block/text 解析。
2. pdfplumber 解析。
3. pypdf 解析。
4. OCR，可选，不作为第一版强依赖。
5. 降级为仅元数据入库。

### 18.2 解析成功判定

正文解析成功需要满足：

1. 提取文本长度 >= 1000 字符。
2. 非空页数量 >= 2。
3. 文本中不全是乱码。
4. 中英文字符比例合理。
5. 不能只有参考文献或页眉页脚。

如果文本长度小于 1000，但论文页数很少，可降级为 `partial`。

### 18.3 PyMuPDF 解析

```python
import fitz

doc = fitz.open(pdf_path)
for page in doc:
    text = page.get_text("text")
```

如果顺序混乱，尝试：

```python
blocks = page.get_text("blocks")
# 按 y 坐标排序
```

### 18.4 pdfplumber 解析

```python
import pdfplumber

with pdfplumber.open(pdf_path) as pdf:
    for page in pdf.pages:
        text = page.extract_text()
```

### 18.5 pypdf 解析

```python
from pypdf import PdfReader

reader = PdfReader(pdf_path)
for page in reader.pages:
    text = page.extract_text()
```

### 18.6 OCR 兜底，可选

OCR 第一版不作为强依赖。

如果实现 OCR：

- 只有文本提取失败且 PDF 疑似扫描件时触发。
- OCR 可配置启用/禁用。
- OCR 失败不影响论文入库。

配置：

```python
ENABLE_OCR_FALLBACK = False
```

### 18.7 解析失败处理

如果所有解析器都失败：

```python
parse_status = "failed"
vector_status = "skipped"
note_status = "none"
```

仍保存：

- `file_path`
- `title`
- `authors`
- `year`
- `language`
- `metadata_warning`

Assistant 回答：

```text
论文已加入个人知识库，但 PDF 正文解析失败，因此暂时无法构建向量索引或生成完整阅读笔记。你仍可以在知识库中看到该论文记录。
```

不要让系统崩溃。

### 18.8 部分解析成功处理

如果解析文本较短，但仍可用：

```python
parse_status = "partial"
vector_status = "partial"
```

允许构建索引，但 Assistant 回答提示：

```text
PDF 正文解析不完整，生成的笔记可能缺少部分章节信息。
```

---

## 19. 中文/英文论文支持

语言字段：

- `zh`
- `en`
- `mixed`
- `unknown`

章节标准化：

| 英文标题 | 标准名 |
|---|---|
| Abstract | abstract |
| Introduction | introduction |
| Related Work | related_work |
| Method / Methodology / Approach | method |
| Experiments / Evaluation | experiment |
| Results | result |
| Discussion | discussion |
| Conclusion | conclusion |
| References | references |

| 中文标题 | 标准名 |
|---|---|
| 摘要 | abstract |
| 引言 / 绪论 | introduction |
| 相关工作 | related_work |
| 方法 / 模型 / 算法 | method |
| 实验 / 实验设置 | experiment |
| 结果 / 结果分析 | result |
| 讨论 | discussion |
| 结论 | conclusion |
| 参考文献 | references |

第一版不用追求完美 PDF 版面恢复，但必须支持中英文基本标题和摘要提取。

---

## 20. RAG 实现

### 20.1 向量库默认选择

第一版默认使用 ChromaDB persistent client。

每条向量 metadata 必须包含：

```json
{
  "source_type": "paper",
  "paper_id": "paper_001",
  "note_id": "",
  "folder_id": "folder_gnn",
  "section_name": "method",
  "chunk_index": 12,
  "title": "...",
  "authors": "..."
}
```

笔记 chunk：

```json
{
  "source_type": "note",
  "paper_id": "paper_001",
  "note_id": "note_001",
  "folder_id": "folder_gnn",
  "section_name": "method",
  "chunk_index": 3,
  "title": "..."
}
```

### 20.2 chunk

中文：

```python
chunk_size = CHUNK_SIZE_ZH  # 900 chars
chunk_overlap = CHUNK_OVERLAP  # 120 chars
```

英文：

```python
chunk_size = CHUNK_SIZE_EN  # 900 chars for MVP
chunk_overlap = CHUNK_OVERLAP
```

说明：第一版可以用字符近似，后续再换 token-aware splitter。

每个 chunk 保存：

- `chunk_id`
- `paper_id`
- `section_name`
- `chunk_index`
- `text`
- `vector_id`

### 20.3 retrieve scope

必须支持四种 scope。

#### paper_only

只检索当前论文 chunks：

```json
{"source_type": "paper", "paper_id": "paper_xxx"}
```

#### note_only

只检索当前笔记 chunks：

```json
{"source_type": "note", "paper_id": "paper_xxx"}
```

#### paper_and_note

同时检索当前论文和当前笔记：

- paper top_k = 5
- note top_k = 3
- 合并后按 score 排序。
- 去重相似文本。

#### global_library

检索全部论文 chunks。第一版可只检索 paper chunks，note chunks 可选加入。

### 20.4 evidence 返回结构

```json
[
  {
    "evidence_id": "ev_001",
    "source_type": "paper",
    "paper_id": "paper_001",
    "note_id": "",
    "title": "...",
    "section": "Method",
    "score": 0.86,
    "text": "..."
  }
]
```

### 20.5 evidence 限制

生成笔记时：

| section | top_k |
|---|---:|
| abstract | 2 |
| method | 5 |
| experiment | 5 |
| result | 5 |
| conclusion | 3 |
| limitation/discussion | 3 |

总 evidence 数不超过：

```python
MAX_EVIDENCE_ITEMS = 20
```

每个 evidence 截断到：

```python
MAX_EVIDENCE_CHARS = 1200
```

---

## 21. DeepSeek Client

文件：`backend/llm/deepseek_client.py`

使用 OpenAI-compatible Chat API 格式。

### 21.1 基本实现

```python
import json
from typing import Any
from openai import OpenAI
from backend import config

class DeepSeekClient:
    def __init__(self):
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY is not set.")
        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=config.DEEPSEEK_TIMEOUT_SECONDS,
            max_retries=config.DEEPSEEK_MAX_RETRIES,
        )

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        response = self.client.chat.completions.create(
            model=model or config.DEEPSEEK_MODEL_CHAT,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        return response.choices[0].message.content or ""

    def json_chat(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=model or config.DEEPSEEK_MODEL_JSON,
            messages=messages,
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            stream=False,
        )
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except Exception:
            return {"_parse_error": True, "raw": content}
```

### 21.2 要求

- API key 从环境变量读取。
- API key 缺失时返回明确错误。
- 支持 timeout。
- 支持异常处理。
- JSON 输出任务使用 `response_format={"type": "json_object"}`。
- JSON prompt 中必须包含 `json` 字样和目标 JSON 示例。
- JSON parse 失败要兜底。
- 对长论文生成要避免单次输入过长。
- 记录 token usage 的 summary，不要把完整 paper_text 写进 trace。

---

## 22. Deep Paper Note Skill

文件：`backend/skills/deep_paper_note_skill.py`

第一版只实现这一个主 Skill。

### 22.1 对外函数

```python
def run_deep_paper_note_skill(
    paper_metadata: dict,
    paper_text: str,
    retrieved_chunks: list,
    target_language: str = "zh",
) -> dict:
    ...
```

MCP 只暴露：

```text
run_deep_paper_note_skill
```

不要暴露 `parse_pdf`、`detect_language`、`split_chunks` 等小 skill。

### 22.2 返回结构

```json
{
  "status": "success",
  "note_markdown": "...",
  "skill_phases": [
    {"phase": "resolve_input", "status": "success"},
    {"phase": "detect_language", "status": "success"},
    {"phase": "normalize_sections", "status": "success"},
    {"phase": "build_evidence_bundle", "status": "success"},
    {"phase": "generate_note_plan", "status": "success"},
    {"phase": "generate_sections", "status": "success"},
    {"phase": "merge_markdown", "status": "success"},
    {"phase": "quality_check", "status": "success"}
  ],
  "quality_check": {
    "has_frontmatter": true,
    "has_basic_info": true,
    "has_summary": true,
    "has_method": true,
    "has_experiment": true,
    "has_limitations": true,
    "has_evidence": true,
    "missing_sections": []
  },
  "fallbacks": []
}
```

### 22.3 内部阶段

- `resolve_input`
- `detect_language`
- `normalize_sections`
- `build_evidence_bundle`
- `generate_note_plan`
- `generate_sections`
- `merge_markdown`
- `quality_check`
- `repair_if_needed`
- `partial_note_fallback`

注意：

- 这是一个主 Skill，不要拆成多个对外 Skill。
- 内部阶段可以拆函数。
- 最终阅读笔记默认中文。
- 英文论文也生成中文阅读笔记。
- Skill 不直接写文件。
- 写入 Obsidian 由 File MCP 完成。
- 不导出 Word。

---

## 23. 长论文生成笔记兜底方案

### 23.1 长论文判定

满足任一条件即视为长论文：

1. full_text 字符数 > `LONG_PAPER_CHAR_THRESHOLD`。
2. chunk 数量 > `LONG_PAPER_CHUNK_THRESHOLD`。
3. 页数 > `LONG_PAPER_PAGE_THRESHOLD`。
4. 单次 prompt 估算 token 超过模型安全阈值。

配置：

```python
LONG_PAPER_CHAR_THRESHOLD = 60000
LONG_PAPER_CHUNK_THRESHOLD = 80
LONG_PAPER_PAGE_THRESHOLD = 30
MAX_CONTEXT_CHARS_PER_LLM_CALL = 16000
```

### 23.2 长论文分阶段策略

长论文不允许一次性生成完整笔记。

流程：

1. `section_summary`
2. `evidence_bundle`
3. `note_plan`
4. `section_note_generation`
5. `note_merge`
6. `quality_check`
7. `repair_if_needed`

### 23.3 section_summary

标准章节：

- `abstract`
- `introduction`
- `related_work`
- `method`
- `experiment`
- `result`
- `discussion`
- `conclusion`

每个章节生成：

```json
{
  "section": "method",
  "summary": "...",
  "key_points": [],
  "important_evidence_ids": []
}
```

如果缺失：

```json
{
  "section": "method",
  "summary": "",
  "missing": true
}
```

不要编造缺失章节。

### 23.4 note_plan

先生成笔记大纲，不直接写全文。

大纲必须包含：

1. 基本信息。
2. 一句话总结。
3. 研究背景。
4. 研究问题。
5. 方法概述。
6. 关键技术细节。
7. 实验设置。
8. 实验结果。
9. 创新点。
10. 局限性。
11. 可复现性分析。
12. 对我课题的启发。
13. 原文证据片段。

如果 evidence 不足，note_plan 中标注：

```text
某部分 evidence 不足，后续生成时应说明不确定性。
```

### 23.5 section_note_generation

分段生成，不要一次性生成整篇 Markdown。

分段调用：

- `generate_basic_info`
- `generate_summary_background`
- `generate_method_section`
- `generate_experiment_section`
- `generate_innovation_limitation`
- `generate_reproducibility_and_insight`
- `generate_evidence_blocks`

每段生成后保存：

```python
state["partial_note_sections"] = {
    "basic_info": "...",
    "method": "...",
    "experiment": "...",
}
```

### 23.6 note_merge

合并时必须：

1. 加 YAML frontmatter。
2. 保持章节顺序。
3. 插入 evidence blocks。
4. 避免重复标题。
5. 清理空章节。

### 23.7 quality_check

检查生成笔记是否包含：

- frontmatter
- 基本信息
- 一句话总结
- 研究背景
- 方法概述
- 实验设置或实验结果
- 创新点
- 局限性
- 可复现性分析
- 对我课题的启发
- 原文证据片段

输出：

```json
{
  "has_frontmatter": true,
  "has_basic_info": true,
  "has_summary": true,
  "has_method": true,
  "has_experiment": true,
  "has_innovations": true,
  "has_limitations": true,
  "has_evidence": true,
  "missing_sections": []
}
```

### 23.8 repair_if_needed

如果质量检查失败，不要重新生成全文，只修复缺失部分。

最多修复：

```python
MAX_NOTE_REPAIR_ROUNDS = 2
```

超过仍失败，输出 partial note，并提示：

```text
笔记已生成，但部分章节 evidence 不足，建议人工检查。
```

### 23.9 长论文失败兜底

如果完整笔记生成失败，降级为结构化摘要笔记，包含：

1. 基本信息。
2. 摘要。
3. 方法初步总结。
4. 实验初步总结。
5. 已检索 evidence。
6. 失败原因。

状态：

```python
note_status = "partial"
```

Assistant 回答：

```text
由于论文较长或部分章节解析不完整，系统已生成降级版 Obsidian 笔记。该笔记包含可用 evidence 和结构化摘要，建议后续人工补充。
```

---

## 24. Obsidian Markdown 模板

生成的 `.md` 必须包含 YAML frontmatter。

```markdown
---
title: "{{title}}"
authors: "{{authors}}"
year: "{{year}}"
language: "{{language}}"
status: "read"
tags:
  - paper
  - reading-note
source_pdf: "{{source_pdf}}"
created: "{{created_at}}"
---

# {{title}}

## 1. 基本信息

- 标题：{{title}}
- 作者：{{authors}}
- 年份：{{year}}
- 语言：{{language}}
- PDF：{{source_pdf}}

## 2. 一句话总结

{{one_sentence_summary}}

## 3. 研究背景

{{background}}

## 4. 研究问题

{{research_questions}}

## 5. 方法概述

{{method_overview}}

## 6. 关键技术细节

{{technical_details}}

## 7. 实验设置

{{experiment_setup}}

## 8. 实验结果

{{experiment_results}}

## 9. 创新点

{{innovations}}

## 10. 局限性

{{limitations}}

## 11. 可复现性分析

{{reproducibility}}

## 12. 对我课题的启发

{{personal_insights}}

## 13. 可链接笔记

- [[Graph Neural Network]]
- [[RAG]]
- [[Agent]]
- [[Paper Reading]]

## 14. 原文证据片段

{{evidence_blocks}}
```

文件保存路径：

```text
obsidian_vault/02_ReadingNotes/{year} - {first_author} - {short_title}.md
```

要求：

- 文件名清理非法字符。
- YAML 字段转义引号和换行。
- 如果 year/author unknown，也要生成稳定文件名。
- 不导出 Word。

---

## 25. finish_node 要求

`finish_node` 必须整理统一响应。

```python
response = {
    "task_id": state["task_id"],
    "answer": state.get("answer") or build_default_answer(state),
    "message_type": infer_message_type(state),
    "current_paper": {
        "paper_id": state.get("current_paper_id"),
        "title": state.get("paper_metadata", {}).get("title"),
    },
    "artifacts": state.get("artifacts", {}),
    "execution": {
        "langgraph_nodes": state.get("langgraph_nodes", []),
        "mcp_tool_calls": state.get("mcp_tool_calls", []),
        "a2a_messages": state.get("a2a_messages", []),
        "skill_phases": state.get("skill_phases", []),
        "rag_evidence": state.get("rag_evidence", []),
        "fallbacks": state.get("fallbacks", []),
    },
}
```

如果 `phase == ERROR`：

```python
message_type = "error"
answer = f"任务执行失败：{state.get('error')}"
```

如果 `status == partial`：

```python
message_type = "partial_success"
answer = answer + "\n\n注意：本次任务使用了降级策略，建议人工检查结果。"
```

---

## 26. 降级展示要求

如果使用兜底策略，前端回答中必须显示。

### 26.1 元数据兜底展示

```text
已将论文加入个人知识库，但系统使用了元数据降级策略：
- 元数据来源：filename_or_identifier
- 元数据置信度：0.45
- PDF 正文解析状态：partial
- 向量索引状态：partial
建议后续人工检查标题和作者信息。
```

### 26.2 长论文分阶段展示

```text
该论文较长，系统已启用长论文分阶段生成策略：
1. 按章节生成摘要
2. 构建 evidence bundle
3. 生成笔记大纲
4. 分段生成笔记
5. 合并 Obsidian Markdown
6. 执行质量检查
```

### 26.3 partial note 展示

```text
已生成降级版阅读笔记。由于部分章节解析不完整，实验结果和局限性部分可能需要人工补充。
```

---

## 27. 开发阶段规划

### Stage 0：项目初始化

目标：

- FastAPI 启动。
- Vue 启动。
- 前后端能通信。
- SQLite 初始化。
- 默认文件夹 `All Papers` 创建。

完成标准：

- `GET /api/health` 返回 ok。
- 前端能显示 Local Research Agent 页面。
- 左侧能看到 `All Papers`。

### Stage 1：左侧知识库 UI + 文件夹 API

目标：

- 创建文件夹。
- 删除空文件夹。
- 显示文件夹。
- 显示当前文件夹论文。
- 按标题/作者搜索论文。

完成标准：

- 用户可以创建 GNN 文件夹。
- 用户可以删除空文件夹。
- 用户不能删除 All Papers。
- 用户不能删除非空文件夹。
- 用户可以搜索论文标题或作者。

### Stage 2：右侧对话框和文件上传

目标：

- 对话 UI 完成。
- 支持输入文本。
- 支持拖拽 PDF。
- 上传 PDF 到后端。
- 后端保存 PDF 到 `data/papers`。
- 实现上传安全检查。

完成标准：

- 拖入 PDF 后 Assistant 回复“已接收 PDF”。
- 文件保存到 `data/papers`。
- 非 PDF 文件被拒绝。

### Stage 3：PDF 解析与元数据兜底

目标：

- 实现多级 PDF 元数据提取。
- 实现正文解析兜底。

任务：

- PDF metadata 读取。
- 首页启发式元数据提取。
- 文件名兜底。
- LLM 辅助元数据提取。
- PyMuPDF / pdfplumber / pypdf 解析链。
- `parse_status: done | partial | failed`。
- 元数据失败时仍允许入库。

完成标准：

1. 正常 PDF 能提取标题、作者、年份、语言。
2. metadata 为空的 PDF 能从首页或文件名兜底。
3. 解析失败的 PDF 仍能以 partial/failed 状态进入知识库。
4. Assistant 回答中能提示解析质量。

### Stage 4：RAG 构建

目标：

- 论文正文 chunk。
- 建立向量索引。
- 保存 `paper_chunks`。
- 支持四种 scope retrieve。

完成标准：

- 论文导入后 `vector_status = done | partial | skipped`。
- 后端可以根据 query 返回 evidence chunks。
- `paper_and_note` scope 可正常合并 evidence。

### Stage 5：MCP 最小集成

目标：

- File MCP Server 可用。
- Database MCP Server 可用。
- RAG MCP Server 可用。
- Skills MCP Server 可用。
- Harness 通过 MCP Client 调工具。
- MCP 调用记录进入 response.execution.mcp_tool_calls。

完成标准：

- 导入论文时回答里能展开看到 MCP 工具调用。
- Agent 代码不直接调用底层 CRUD、RAG、文件写入函数。

### Stage 6：LangGraph 条件流转

目标：

- 实现明确 phase / needs_evidence / 条件边。
- 避免节点循环混乱。

任务：

- 更新 AgentState。
- 实现 phase 枚举。
- 实现 task_type 到 phase 映射。
- 实现纯 router。
- 实现 node_visit_count 防循环。
- 实现五条标准流程。

完成标准：

1. 每个任务类型路径固定、可预测。
2. 不出现无限循环。
3. `import_and_note` 能正确进入 Knowledge RAG Agent 两次。
4. `generate_note` 和 chat 都先检索 evidence，再生成。
5. 回答中能看到完整 LangGraph 节点轨迹。

### Stage 7：Deep Paper Note Skill 与长论文兜底

目标：

- 实现主 Skill。
- 支持长论文分阶段生成。
- 支持降级输出。

任务：

- `run_deep_paper_note_skill`。
- 短论文普通生成。
- 长论文判定。
- `section_summary`。
- `evidence_bundle`。
- `note_plan`。
- `section_note_generation`。
- `note_merge`。
- `quality_check`。
- `repair_if_needed`。
- `partial_note_fallback`。

完成标准：

1. 普通论文能生成完整 Obsidian Markdown。
2. 长论文不会因上下文过长直接失败。
3. 长论文能分章节生成并合并。
4. 缺失章节能自动 repair。
5. 失败时能生成 partial note。
6. Assistant 回答中能显示降级原因和 Skill 阶段。

### Stage 8：论文 / 笔记 / 全知识库问答

目标：

- 当前论文问答。
- 当前笔记问答。
- 当前论文 + 当前笔记问答。
- 全知识库问答。
- A2A-style 消息记录。
- RAG evidence 展示。

完成标准：

- 用户可以问：“这篇论文的方法怎么理解？”
- 系统基于当前论文 evidence 回答。
- 用户可以切换到全知识库问答。
- 系统基于多篇论文 evidence 回答。
- evidence 为空时有可靠性提示。

### Stage 9：演示打磨

目标：

- 准备英文论文 demo。
- 准备中文论文 demo。
- 准备一个元数据不完整或解析不佳的 PDF。
- 准备 Obsidian Vault。
- 保证回答中可展开：LangGraph / MCP / A2A-style / RAG Evidence / Deep Paper Note Skill / fallback。
- 修复错误提示。

完成标准：

- 可以完成完整比赛演示。

---

## 28. 验收标准

### 28.1 UI 验收

- 只有一个主页面。
- 左侧是个人知识库。
- 右侧是对话框。
- 支持拖入 PDF。
- 支持创建文件夹。
- 支持删除空文件夹。
- 不能删除 All Papers。
- 不能删除非空文件夹。
- 支持按标题和作者搜索论文。
- 回答中能折叠显示执行过程。

### 28.2 功能验收

- 能导入中文 PDF。
- 能导入英文 PDF。
- 能写入本地数据库。
- 元数据缺失时能兜底入库。
- 正文解析失败时能降级入库。
- 能构建向量索引。
- 能生成 Obsidian Markdown 阅读笔记。
- 长论文能分阶段生成笔记。
- 长论文失败时能生成 partial note。
- 能围绕当前论文问答。
- 能围绕当前笔记问答。
- 能围绕当前论文 + 当前笔记问答。
- 能围绕全知识库问答。

### 28.3 技术验收

- 使用 LangGraph 管理两个 Agent 节点。
- 使用 phase / needs_evidence / evidence_ready / note_ready 控制流程。
- router 函数不修改 state。
- 有 node_visit_count 防循环。
- 使用 MCP 调用工具。
- 有 Knowledge RAG Agent Node。
- 有 Note Skill Agent Node。
- 有 A2A-style 消息记录。
- 只有一个主 Skill：Deep Paper Note Skill。
- 所有执行过程能在 Assistant 回答中看到。
- Agent 不绕过 Harness 直接调用底层函数。

### 28.4 输出验收

- 不导出 Word。
- 只导出 Markdown。
- Markdown 可放入 Obsidian Vault。
- Markdown 包含 YAML frontmatter。
- Markdown 包含论文基本信息、方法、实验、创新点、局限性、启发和 evidence。
- 如果是降级笔记，必须说明降级原因。

---

## 29. 演示脚本

### Step 1：打开系统

展示：

- 左侧 Personal Library。
- 右侧 Research Chat。

说明：

```text
这是一个单页对话式科研 Agent 系统。
```

### Step 2：创建文件夹

在左侧创建：

- GNN
- Bitcoin
- Agent

说明：

```text
个人知识库支持最简文件夹组织。
```

### Step 3：导入英文论文

选中 GNN 文件夹，把英文 PDF 拖入对话框。

Assistant 应回答：

```text
已将论文《xxx》加入个人知识库。
所属文件夹：GNN
语言：英文
状态：已解析、已向量化。
```

展开：

- LangGraph 执行过程。
- MCP 工具调用。
- RAG 构建记录。

### Step 4：导入中文论文

选中 Bitcoin 文件夹，把中文 PDF 拖入对话框。

Assistant 应回答：

```text
已将论文《xxx》加入个人知识库。
所属文件夹：Bitcoin
语言：中文
状态：已解析、已向量化。
```

说明：

```text
系统支持中文论文和英文论文。
```

### Step 5：搜索论文

在左侧搜索框输入论文标题或作者名。

说明：

```text
搜索只按标题和作者进行。
```

### Step 6：生成 Obsidian 笔记

输入：

```text
请为当前论文生成一份 Obsidian 阅读笔记。
```

Assistant 应回答：

```text
已生成 Obsidian Markdown 阅读笔记。
路径：obsidian_vault/02_ReadingNotes/xxx.md
```

展开：

- Deep Paper Note Skill 阶段。
- RAG Evidence。
- MCP 工具调用。
- A2A-style Agent 通信。
- LangGraph 执行过程。

打开 Obsidian，展示生成的 `.md`。

### Step 7：当前论文问答

输入：

```text
这篇论文的方法部分怎么理解？
```

Assistant 基于当前论文 evidence 回答。

展开：

- RAG Evidence。
- A2A-style Agent 通信。

### Step 8：当前论文 + 当前笔记问答

切换问答范围为：

```text
当前论文 + 当前笔记
```

输入：

```text
结合论文和我的阅读笔记，总结这篇论文最值得复现的部分。
```

Assistant 同时基于 paper chunks 和 note chunks 回答。

### Step 9：全知识库问答

切换问答范围为：

```text
全知识库
```

输入：

```text
基于我的知识库，总结一下 Top-K 在图神经网络中的常见作用。
```

Assistant 基于多篇论文 evidence 回答。

说明：

```text
系统不是一次性摘要工具，而是本地科研知识库 Agent。
```

### Step 10：兜底策略展示

准备一个元数据不完整或解析不理想的 PDF。

拖入系统后，Assistant 应提示：

```text
论文已加入知识库，但元数据提取不完整，标题/作者可能需要人工修改。
```

展开 execution，展示：

- `metadata_source`
- `metadata_confidence`
- `parse_status`
- `parse_warning`

说明：

```text
系统具有 PDF 元数据提取、正文解析失败和长论文生成的兜底策略。
```

---

## 30. README 要求

`README.md` 中写清楚：

1. 项目名称：Local Research Agent。
2. 功能简介。
3. 技术栈。
4. 如何配置 DeepSeek API key。
5. 如何启动后端。
6. 如何启动前端。
7. 如何设置 Obsidian Vault 路径。
8. 演示流程。
9. 当前限制：
   - 文件夹只支持创建和删除空文件夹。
   - 搜索只支持标题和作者。
   - 不支持 Word 导出。
   - 第一版只支持一个 Deep Paper Note Skill。
   - OCR 兜底默认关闭。
   - PDF 解析可能存在 partial 状态。
   - MCP 第一版使用本地同进程/挂载式运行，不启动四个独立服务进程。

---

## 31. 启动命令

### 31.1 后端 Linux / macOS

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DEEPSEEK_API_KEY="your_api_key"
export OBSIDIAN_VAULT_PATH="../obsidian_vault"
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 31.2 后端 Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DEEPSEEK_API_KEY="your_api_key"
$env:OBSIDIAN_VAULT_PATH="../obsidian_vault"
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 31.3 前端

```bash
cd frontend
npm install
npm run dev
```

---

## 32. requirements.txt 建议

```text
fastapi
uvicorn[standard]
pydantic
pydantic-settings
sqlalchemy
python-multipart
openai
langgraph
mcp[cli]
PyMuPDF
pdfplumber
pypdf
chromadb
sentence-transformers
numpy
python-dotenv
```

可选：

```text
pytesseract
pdf2image
```

OCR 依赖不要默认启用。

---

## 33. Codex 实现硬性要求

实现时必须遵守：

1. 不允许 PDF 解析失败导致整个系统崩溃。
2. 不允许元数据缺失导致论文无法入库。
3. 不允许长论文一次性塞进 DeepSeek。
4. 不允许 LangGraph 条件边没有明确 phase。
5. 不允许 router 函数修改 state。
6. 不允许两个 Agent 节点之间无限循环。
7. 不允许 Note Skill Agent 直接绕过 Knowledge RAG Agent 检索 paper evidence。
8. 不允许 Knowledge RAG Agent 生成最终阅读笔记。
9. 不允许多个 Skill 暴露给 MCP，第一版只暴露 `run_deep_paper_note_skill`。
10. 所有降级策略必须在 Assistant 回答中说明。
11. 所有降级策略必须写入 execution 信息，便于前端折叠展示。
12. 不允许做多页面前端。
13. 不允许做文件夹拖拽。
14. 不允许做 Word 导出。
15. 不允许把 DeepSeek API key 写死。
16. 不允许上传文件路径穿越。
17. 不允许任意文件写入 Obsidian Vault 外部目录。
18. 不允许 trace 中保存完整 API key 或完整超长论文正文。

---

## 34. 给 Codex 的推荐实现顺序

建议按以下顺序提交任务给 Codex，不要一次性让它实现全系统：

1. 初始化项目结构、FastAPI、Vue、SQLite schema。
2. 实现 folders / papers 基础 API 和前端左侧 UI。
3. 实现 PDF 上传安全检查和保存。
4. 实现 PDF 元数据提取、正文解析和入库。
5. 实现 chunker、embedding、Chroma persistent vector store。
6. 实现 MCP servers 和 ToolGateway，把已有服务包装成 MCP tools。
7. 实现 LangGraph state、builder、两个 Agent node、finish_node。
8. 实现 DeepSeekClient 和 JSON 兜底。
9. 实现 Deep Paper Note Skill 短论文生成。
10. 实现长论文分阶段生成、quality_check、repair、partial note。
11. 实现 chat_scope 四类问答。
12. 实现 execution 折叠展示。
13. 准备 demo 数据和 README。

---

## 35. 最终一句话

请实现一个最小但完整的 Local Research Agent：左侧是最简个人论文库，支持创建文件夹、删除空文件夹、按标题和作者搜索论文；右侧是 Agent 对话框，支持拖入 PDF、生成 Obsidian Markdown 阅读笔记，以及当前论文、当前笔记、当前论文 + 当前笔记、全知识库问答。后端通过 Harness 调用 LangGraph，LangGraph 用 phase / needs_evidence / evidence_ready / note_ready 管理 Knowledge RAG Agent Node 和 Note Skill Agent Node，底层通过 MCP 调用文件、数据库、RAG 和 Deep Paper Note Skill。PDF 元数据提取、正文解析失败和长论文笔记生成必须有兜底方案。所有 LangGraph、MCP、A2A-style、RAG、Skill 和降级信息都在 Assistant 回答中折叠展示。
