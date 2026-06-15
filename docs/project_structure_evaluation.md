# Local Research Agent 项目结构与实现状态评估报告

## 1. 总体评估

当前 Local Research Agent 已经具备本地科研论文 Agent 系统的主要骨架：后端有 LangGraph 风格工作流、Knowledge RAG Agent、Note Skill Agent、Adaptive Layout-Aware RAG v2、ToolGateway/MCP 调用记录、会话持久化和 execution payload；前端有论文库、聊天界面和 execution panel。

P0/P1/P2 已完成第一轮收敛：上传和聊天 API 统一进入 `backend/harness/runtime.py`，execution payload 构建与保存下沉到 `backend/harness/execution_builder.py`，chat history 能恢复历史 assistant message 的 `execution_json`，删除 paper 会清理 paper/note vectors，Database MCP 已补齐关键具名工具，trace/MCP/A2A 统一使用 shared redaction helper，前端 execution payload 也已完成类型收紧和可读展示。

当前最大结构短板仍是 `backend/app.py`：它保留较多 graph runner callbacks、RAG handler、note handler 和 PDF ingest 业务编排。下一阶段应继续向 Harness/Agent service 层下沉。

## 2. 当前项目结构总览

```text
README.md
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

## 3. 关键模块状态

| 模块 | 当前代码状态 | 完成度 | 后续问题 | 优先级 |
|---|---|---|---|---|
| Harness Runtime | `backend/harness/runtime.py` 提供 `run_upload_task()` / `run_chat_task()` 并被 API 调用 | 已完成 P0 | deeper graph handlers 仍在 `app.py` | Done |
| LangGraph 风格 Agent 编排 | `backend/graph/`、`backend/agents/` 存在，节点路由可运行 | 已完成 | Agent 节点偏薄，业务 handler 仍较多在 `app.py` | P1/P3 |
| ToolGateway / MCP | `backend/tool_gateway.py` 记录调用，Database MCP 已补齐关键具名工具 | 已完成 P1 | 更深层业务编排仍可继续收敛 | Done |
| Adaptive Layout-Aware RAG v2 | `backend/adaptive_rag/`、`layout_parser.py`、`semantic_chunker.py`、`structured_retriever.py` 已存在 | 已完成 | 不应再把 `backend/rag/` 写作当前目录 | Done |
| Note Skill Agent v1.4 | `backend/note_skill.py` 与 `backend/app.py.generate_note()` 串起主流程 | 已完成 | orchestration 仍在 `app.py` | P1/P3 |
| Chat sessions | `backend/chat_sessions.py`、`chat_sessions`、`agent_tasks.session_id`、session API 存在 | 已完成 P0 | 可继续做 UX 优化 | Done |
| Execution panel | `ExecutionPanel.vue` 已改为 `ExecutionPayload` typed prop，并提供结构化摘要 | 已完成 P2 | 后续可做更精细 UI，但不是结构阻塞 | Done |
| 前端主界面 | `MainChatView.vue` 保留现有 API/state 逻辑，已清理可见乱码 | 已完成 P2 | 暂不拆 `api/` 和 stores | Done |
| 文档收敛 | README 与 docs 下正式开发文档已同步 P0/P1/P2 | 已完成 P2 | 后续新增阶段文档应进入 docs 或路线图 | Done |

## 4. 当前明确不创建的目录

| 路径 | 当前状态 |
|---|---|
| `backend/rag/` | 不存在；真实实现为 `backend/adaptive_rag/`、`backend/structured_retriever.py`、`backend/rag.py` |
| `backend/skills/` | 不存在；真实 Skill 实现在 `backend/note_skill.py` |
| `backend/database/` | 不存在；真实数据库实现为 `backend/database.py` 和 `backend/schema.sql` |
| `frontend/src/api/` | 不存在；请求逻辑目前主要在 `MainChatView.vue` |
| `frontend/src/stores/` | 不存在；状态目前主要在 `MainChatView.vue` |

## 5. P0/P1/P2 验收状态

| 阶段 | 目标 | 涉及文件 | 当前验收状态 |
|---|---|---|---|
| P0 | Harness Runtime 成为上传和聊天统一入口 | `backend/harness/runtime.py`、`backend/app.py`、`backend/graph/` | 已完成 |
| P0 | chat history 恢复 execution | `backend/chat_sessions.py`、`frontend/src/views/MainChatView.vue`、`frontend/src/types.ts` | 已完成 |
| P0 | 删除 paper 时清理 vector records | `backend/vector_store.py`、`backend/app.py`、`backend/tests/` | 已完成 |
| P1 | 收敛 ToolGateway 调用边界 | `backend/tool_gateway.py`、`backend/app.py`、`backend/mcp_servers/` | 已完成 |
| P1 | Database MCP 补齐缺失工具 | `backend/mcp_servers/database_mcp_server.py` | 已完成 |
| P1 | trace / MCP / A2A 统一脱敏 | `backend/harness/context_manager.py`、`backend/database.py`、`backend/tool_gateway.py` | 已完成 |
| P2 | execution payload 前端类型增强 | `frontend/src/types.ts`、`frontend/src/components/ExecutionPanel.vue` | 已完成 |
| P2 | execution panel 可读性增强 | `frontend/src/components/ExecutionPanel.vue` | 已完成 |
| P2 | 主界面乱码清理与文档同步 | `frontend/src/views/MainChatView.vue`、`README.md`、`docs/` | 已完成 |

## 6. 下一步建议

| 目标 | 涉及文件 | 建议 |
|---|---|---|
| 继续 app.py 变薄 | `backend/app.py`、`backend/harness/`、`backend/agents/` | 迁移 `run_upload_graph()`、`run_chat_graph()` 或其中一个 handler |
| 清理兼容 facade | `backend/mcp_client/client_manager.py`、`backend/mcp_client/tool_invoker.py` | 确认无外部依赖后再删除 |
| 前端分层 | `frontend/src/views/MainChatView.vue` | 等功能继续增长后再拆 `api/` 或 stores |

## 7. 文档一致性结论

当前正式文档入口保持为：

- `README.md`：面向使用和启动，描述真实结构和当前限制。
- `docs/development_roadmap.md`：面向下一阶段开发，列出 P0/P1/P2 与暂不做。
- `docs/project_structure_evaluation.md`：面向结构评估，说明当前实现、缺口和优先级。

三者都应以当前真实结构为准：`backend/adaptive_rag/`、`backend/note_skill.py`、`backend/database.py`、`backend/schema.sql`、`backend/tool_gateway.py`、`backend/harness/`、`backend/mcp_servers/`、`frontend/src/components/ExecutionPanel.vue`、`frontend/src/views/MainChatView.vue`。
