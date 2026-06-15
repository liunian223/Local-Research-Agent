# Local Research Agent 后续开发路线图

## 1. 当前保留的核心能力

- Adaptive Layout-Aware RAG v2
- Note Skill Agent v1.4
- LangGraph 风格 Agent 编排
- ToolGateway / MCP 调用记录
- execution payload
- Chat sessions
- Obsidian note generation

## 2. 已完成 P0

- Harness Runtime 成为上传和聊天统一入口。
- `backend/harness/execution_builder.py` 接管 execution payload 构建和保存。
- chat history 恢复 historical assistant message 的 `execution_json`。
- 删除 paper 时清理 paper vectors 和 note vectors。

## 3. 已完成 P1

- 收敛关键 ToolGateway 调用边界。
- Database MCP 补齐 `insert_paper`、`insert_chunks`、`delete_paper_artifacts`、note insert、note chunks、paper status 更新等具名工具。
- upload / note / delete 的关键数据库写入走具名 MCP wrapper。
- trace / MCP / A2A 统一使用 shared redaction helper。
- 继续避免新增无意义目录。

## 4. 已完成 P2

- `frontend/src/types.ts` 已补齐 `ExecutionPayload`、Harness、retrieval、evidence bundle、note generation 等前端类型。
- `frontend/src/components/ExecutionPanel.vue` 不再使用 `execution: any`，改为 typed payload，并把 Harness、ToolGateway、RAG、Evidence、Note Skill 的高频字段做结构化摘要。
- `frontend/src/views/MainChatView.vue` 清理了可见中文乱码，保留原有会话、上传、检索和快速笔记交互。
- 正式开发文档恢复为可读中文，并同步 P0/P1/P2 的真实完成状态。

## 5. 本轮新增收敛

- `backend/chat_sessions.py` 承接 chat session、history、execution restore 相关持久化逻辑。
- `backend/app.py` 的 chat session endpoints 变为薄 API wrapper。
- `backend/graph_runtime.py` wrapper 已删除；`standard_flow()`、`validate_node_visits()` 已合并回 `backend/graph/builder.py`。
- 前端 execution panel 已从弱类型 raw JSON 展示，收敛为“结构化摘要 + 原始 JSON 排查详情”。

## 6. 下一步建议

- 继续让 `backend/app.py` 变薄：优先迁移 `run_upload_graph()`、`run_chat_graph()` 或其中一个 handler 到 Harness/Agent service 层。
- 继续清理兼容 facade：评估 `backend/mcp_client/client_manager.py` 和 `backend/mcp_client/tool_invoker.py` 是否仍有外部依赖。
- 只在确实需要时做前端分层，暂不主动拆 `frontend/src/api` 和 stores。

## 7. 暂不做

- 不拆 `frontend/src/api` 和 stores。
- 不拆 `backend/database` 包。
- 不强行新建 `backend/rag` 包。
- 不做独立 MCP server 进程。
