# Harness Design

Local Research Agent 的 Harness 是运行时外壳，不是新的 Agent。它负责把用户请求变成可追踪的任务，把 LangGraph 节点、ToolGateway 调用、MCP-style 工具结果、A2A-style 消息、RAG evidence 和 fallback 决策收束到同一个 `execution` payload。

## 职责边界

- `backend/harness/runtime.py` 创建 `agent_tasks`、决定 `task_type`、保存最终 `execution_json`。
- `backend/harness/graph_runner.py` 驱动当前 LangGraph 风格节点流，并写入 `execution.langgraph_nodes`。
- `backend/tool_gateway.py` 是工具调用边界。Knowledge RAG Agent 和 Note Skill Agent 通过它调用 file/database/rag/skills/vision 工具，调用结果写入 `execution.mcp_tool_calls`。
- `backend/harness/decisions.py` 记录显性决策，最终暴露为 `execution.harness_decisions`。每条包含 `stage`、`decision`、`reason`、`agent`、`tool`、`status`。
- `backend/harness/execution_builder.py` 汇总 `execution.harness`、`execution.harness_decisions`、`execution.mcp_tool_calls`、`execution.a2a_messages`、`execution.rag_evidence`、`execution.evidence_bundle`、`execution.fallbacks`。

Harness 不直接替代 LangGraph、RAG 或 Note Skill。它的目标是让一次运行可解释：为什么路由到某个任务、哪些工具被允许、何时启用 fallback、哪些 evidence 进入答案或笔记。

## 与核心组件的关系

`execution.harness_decisions` 记录决策层：

- `task_routing`: upload/chat 消息被路由为 `import_and_note`、`paper_chat`、`generate_note`、`vision_chat` 等。
- `file_security`: PDF 保存路径是否留在 `PAPER_DIR` 内。
- `tool_policy`: ToolGateway policy 对每个 MCP-style tool 的 allow/deny。
- `fallback`: 由最终 `execution.fallbacks` 归一化而来，例如模型失败、本地模板降级、无图像改用文本 RAG。

`execution.mcp_tool_calls` 记录执行层：

- 文件工具：保存 PDF、写 Markdown note、复制附件。
- 数据库工具：插入 paper/chunks/note、更新 paper status。
- RAG 工具：检索、构建向量索引。
- Skills 工具：`run_deep_paper_note_skill`。

`execution.a2a_messages` 记录 Agent 间交接：

- `paper_imported`
- `evidence_bundle_ready`
- `final_evidence_bundle_ready`

`execution.rag_evidence` 和 `execution.evidence_bundle` 记录证据层：前者是检索到的扁平 evidence，后者按 text/abstract/table/figure/page 等分组，用于回答、笔记和 ExecutionPanel 展示。

## Upload + Note 流程

```text
User uploads PDF with note intent
  -> Harness runtime creates task and records task_routing
  -> LangGraph coordinator_node
  -> Knowledge RAG Agent import node
       -> file_security decision
       -> ToolGateway policy decisions
       -> save PDF, parse text/layout, insert chunks, build vector index
       -> A2A paper_imported
  -> Knowledge RAG Agent retrieval node
       -> retrieve paper evidence
       -> execution.rag_evidence
       -> A2A evidence_bundle_ready
  -> Note Skill Agent generate_note node
       -> run_deep_paper_note_skill
       -> model_note_generation if configured
       -> fallback decisions if model/template downgrade occurs
       -> write note and note chunks
       -> A2A final_evidence_bundle_ready
  -> execution_builder stores execution_json
```

## Paper Chat 流程

```text
User asks question about current paper
  -> Harness runtime creates task and records task_routing
  -> LangGraph coordinator_node
  -> Knowledge RAG Agent retrieval node
       -> ToolGateway policy decisions
       -> adaptive retrieval over current paper
       -> execution.rag_evidence and execution.evidence_bundle
       -> A2A evidence_bundle_ready
  -> Note Skill Agent answer node
       -> optional LLM answer
       -> local RAG fallback if model call fails
       -> fallback decision recorded
  -> execution_builder stores execution_json
```

## Reading The Payload

For demos and debugging, inspect these fields together:

- `execution.harness.runtime_status`: final task state.
- `execution.harness_decisions`: why the system routed, allowed tools, or fell back.
- `execution.mcp_tool_calls`: what actually ran and whether it failed.
- `execution.rag_evidence`: evidence retrieved for the task.
- `execution.evidence_bundle`: evidence grouped for display and generation.
- `execution.fallbacks`: compact compatibility list of fallback labels.

