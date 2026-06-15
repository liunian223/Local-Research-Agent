# Python 文件收敛审计报告

## 0. 当前状态更新

本审计报告中的 `backend/graph_runtime.py` 收敛建议已经完成：`standard_flow()` 和 `validate_node_visits()` 已合并到 `backend/graph/builder.py`，相关 import 已迁移，`backend/graph_runtime.py` 已删除。后续仍可评估 `backend/mcp_client/client_manager.py` 和 `backend/mcp_client/tool_invoker.py` 这两个兼容 facade 是否存在外部依赖；未确认前不建议删除。

## 1. 总体结论

本轮只做审计，没有删除文件、没有重构业务逻辑。当前 Python 层没有发现明显的 `_old.py`、`_bak.py`、`_tmp.py`、`legacy_*.py`、`test_*.py.bak` 这类开发中间版本文件。项目里确实存在几个兼容 wrapper 或桥接文件，例如 `backend/graph_runtime.py`、`backend/harness/runtime.py`、`backend/mcp_client/client_manager.py`、`backend/mcp_client/tool_invoker.py`，但它们不能仅凭名字直接删除。

当前结论是：没有发现可以无条件直接删除的核心 Python 文件。唯一可作为“安全删除候选”进一步确认的是 `backend/graph/checkpoint.py`，它当前没有 import 引用，也没有测试引用，但它属于 graph 包下的辅助快照函数，不是旧版临时文件；建议先确认是否还计划用于 LangGraph checkpoint / state snapshot，再决定是否删除。

更重要的收敛方向是“合并 wrapper”和“迁移 import”。其中 `graph_runtime.py` 的 helper 已经合并到 `backend/graph/builder.py`，wrapper 也已经删除；`backend/mcp_client/` 目前只是 ToolGateway facade，可以在主流程统一直接使用 `backend/tool_gateway.py` 后再删除。`backend/rag.py`、`backend/structured_retriever.py`、`backend/note_skill.py`、`backend/database.py`、`backend/tool_gateway.py` 都仍在当前主流程或测试中使用，不能删除。

本轮已执行检查：

```text
git status --short
Get-ChildItem -Recurse -Filter *.py | Select-Object FullName
rg "graph_runtime"
rg "import rag|from rag"
rg "import structured_retriever|from structured_retriever"
rg "import note_skill|from note_skill"
rg "import tool_gateway|from tool_gateway"
rg "mcp_client"
rg "harness.runtime"
rg "client_manager"
rg "tool_invoker"
```

当前 `git status --short` 显示工作区已有大量未提交改动和新增文件，包括 `README.md`、后端 RAG/Harness/Note Skill/Test 相关文件、前端 execution panel 相关文件，以及 `docs/` 文档。后续删除任何 Python 文件前必须继续尊重这些未提交改动，避免误删用户或前序开发成果。

## 2. 当前 Python 文件清单

主要后端文件：

```text
backend/app.py
backend/config.py
backend/database.py
backend/deepseek_client.py
backend/graph_runtime.py
backend/layout_parser.py
backend/note_skill.py
backend/pdf_tools.py
backend/rag.py
backend/semantic_chunker.py
backend/structured_retriever.py
backend/tool_gateway.py
backend/vector_store.py
```

Adaptive RAG：

```text
backend/adaptive_rag/__init__.py
backend/adaptive_rag/abstract_detector.py
backend/adaptive_rag/abstract_policy.py
backend/adaptive_rag/adaptive_retriever.py
backend/adaptive_rag/evidence_checker.py
backend/adaptive_rag/evidence_fusion.py
backend/adaptive_rag/hybrid_retriever.py
backend/adaptive_rag/query_analyzer.py
backend/adaptive_rag/reranker.py
```

Agent / graph / harness：

```text
backend/agents/__init__.py
backend/agents/knowledge_rag_agent.py
backend/agents/note_skill_agent.py
backend/graph/__init__.py
backend/graph/builder.py
backend/graph/checkpoint.py
backend/graph/state.py
backend/harness/__init__.py
backend/harness/context_manager.py
backend/harness/execution_builder.py
backend/harness/fallback_manager.py
backend/harness/policy.py
backend/harness/runtime.py
backend/harness/security.py
```

LLM / MCP：

```text
backend/llm/__init__.py
backend/llm/codex_cli_client.py
backend/llm/model_gateway.py
backend/llm/openai_client.py
backend/mcp_client/__init__.py
backend/mcp_client/client_manager.py
backend/mcp_client/tool_invoker.py
backend/mcp_servers/__init__.py
backend/mcp_servers/database_mcp_server.py
backend/mcp_servers/file_mcp_server.py
backend/mcp_servers/rag_mcp_server.py
backend/mcp_servers/skills_mcp_server.py
```

测试：

```text
backend/tests/conftest.py
backend/tests/test_acceptance.py
backend/tests/test_harness_execution_payload.py
backend/tests/test_harness_policy.py
backend/tests/test_harness_redaction.py
backend/tests/test_harness_runtime.py
backend/tests/test_note_skill_agent_answer_chat.py
backend/tests/test_note_skill_agent_evidence_bundle.py
backend/tests/test_note_skill_agent_generate_note.py
backend/tests/test_note_skill_note_index.py
backend/tests/test_note_skill_quality_repair.py
backend/tests/test_rag_abstract_detector.py
backend/tests/test_rag_adaptive_retriever.py
backend/tests/test_rag_complex_retrieval.py
backend/tests/test_rag_execution_payload.py
backend/tests/test_rag_query_analyzer.py
backend/tests/test_tool_gateway.py
```

未发现以下模式的 Python 临时文件：

```text
*_old.py
*_new.py
*_backup.py
*_bak.py
*_v1.py
*_v2.py
*_review.py
*_temp.py
*_tmp.py
legacy_*.py
test_*.py.bak
```

## 3. 可以直接删除的文件

没有发现可直接删除的 Python 文件。

严格按“无 import、非启动链路、非测试引用、无 side effect、非 README 当前结构、删除不影响 PDF/RAG/Note/Session/Execution”的标准，本轮不建议直接删除任何核心 Python 文件。

| 文件 | 原因 | 是否有 import | 风险 | 建议操作 |
|---|---|---|---|---|
| 无 | 未发现满足全部安全删除条件的核心 Python 文件 | 无 | 无 | 本轮不删除 |
| `backend/graph/checkpoint.py` | 当前搜索未发现引用，内容是 `snapshot_state()`，会脱敏 `uploaded_file_bytes` 和 `paper_text` | 未发现 | 低到中；可能是未来 checkpoint/state snapshot 预留能力 | 不建议本轮直接删；若下一轮确认无计划使用，可作为 Round 1 安全删除候选 |

## 4. 需要合并后删除的文件

| 文件 | 当前作用 | 合并到哪里 | 需要修改哪些 import | 删除前验收 |
|---|---|---|---|---|
| `backend/graph_runtime.py` | 已完成：helper 已合并到 `backend/graph/builder.py`，文件已删除 | 无 | import 已迁移到 `graph.builder` | 已验收 |
| `backend/harness/runtime.py` | 已实化为 upload/chat runtime controller | 不删除 | `backend/app.py` API endpoints 调用 `run_upload_task()` / `run_chat_task()` | 已验收 |
| `backend/mcp_client/client_manager.py` | `create_tool_gateway(conn, task_id)` 的轻量 facade | 直接使用 `backend/tool_gateway.py`，或未来 Harness Runtime 的 gateway factory | 当前未发现主流程 import，但属于 `mcp_client` 兼容层 | 若删除，需确认没有外部脚本/测试依赖；全量 tests 通过 |
| `backend/mcp_client/tool_invoker.py` | re-export `ToolGateway` | 直接使用 `backend/tool_gateway.py` | 当前未发现主流程 import，但 `rg` 显示文件本身引用 `ToolGateway` | 若删除，需确认没有外部脚本/测试依赖；全量 tests 通过 |

## 5. 暂时不能删除的文件

| 文件 | 为什么不能删 | 被谁引用 | 后续如何收敛 |
|---|---|---|---|
| `backend/app.py` | 当前 FastAPI 启动和主编排入口 | uvicorn/FastAPI，项目主流程 | P0 中让 Harness Runtime 接管上传/聊天，逐步变薄 |
| `backend/database.py` | SQLite 初始化、迁移、日志、数据访问 | 多个后端模块和测试 | 不拆包；后续只收敛 CRUD/MCP 边界 |
| `backend/schema.sql` | 数据库 schema，不是 Python 文件但属于启动/迁移关键资产 | `database.py` 初始化读取 | 不能删除 |
| `backend/tool_gateway.py` | 当前真实 ToolGateway | `backend/app.py`、`backend/mcp_client/*`、`backend/tests/test_tool_gateway.py` | 保留；可未来 re-export 到 harness，但不要删除真实实现 |
| `backend/rag.py` | `split_chunks`、`score_chunks`、`note_to_chunks` 仍被使用 | `backend/app.py`、`backend/vector_store.py`、`backend/adaptive_rag/hybrid_retriever.py`、`backend/tests/test_note_skill_note_index.py` | 可将函数迁移到更明确模块后再删；当前不能删 |
| `backend/structured_retriever.py` | 当前 app 与 adaptive RAG 的桥接层，也承担 legacy fallback / evidence bundle / pipeline summary | `backend/app.py`、`backend/adaptive_rag/*` | 等 Adaptive RAG 完全接管后再拆分或合并 |
| `backend/note_skill.py` | 当前真实 Note Skill 实现 | `backend/app.py`、`backend/mcp_servers/skills_mcp_server.py`、多份 Note Skill tests | 不为了目录美观移动；若未来移动，必须同步所有 import 和测试 |
| `backend/vector_store.py` | Chroma/local keyword fallback 入口 | `backend/app.py`、`structured_retriever.py`、`adaptive_rag/hybrid_retriever.py`、`mcp_servers/rag_mcp_server.py` | 后续补 delete_by_paper_id/delete_by_note_id |
| `backend/layout_parser.py` | PDF layout parsing 和 artifact 写入 | `backend/app.py`、`backend/tests/test_rag_abstract_detector.py` 间接相关 | 保留；后续将 artifact 写入纳入 ToolGateway |
| `backend/semantic_chunker.py` | semantic chunk、document row、paper chunk row 构建 | `backend/app.py` | 保留 |
| `backend/pdf_tools.py` | PDF 元数据、文本解析、安全文件名、sha256 | `backend/app.py`、`backend/note_skill.py`、`backend/mcp_servers/file_mcp_server.py` | 保留 |
| `backend/deepseek_client.py` | LLMResult、DeepSeek client、prompt builder 兼容 | `backend/app.py`、`backend/llm/model_gateway.py`、`backend/llm/openai_client.py`、`backend/llm/codex_cli_client.py` | 若未来重命名为 generic llm types，需要迁移多处 import |
| `backend/llm/model_gateway.py` | 当前统一模型网关 | `backend/app.py`、测试/配置检查 | 保留 |
| `backend/llm/openai_client.py` | OpenAI provider | `model_gateway.py` | 保留 |
| `backend/llm/codex_cli_client.py` | Codex CLI provider | `model_gateway.py`、`test_acceptance.py` | 保留 |
| `backend/mcp_servers/*.py` | in-process MCP wrapper | ToolGateway 调用和 app orchestration | 保留；后续补齐 Database MCP 工具 |
| `backend/adaptive_rag/*.py` | RAG v2 当前真实实现 | `layout_parser.py`、`structured_retriever.py`、RAG tests | 保留 |
| `backend/agents/*.py` | LangGraph agent node entrypoints | `backend/app.py`、graph flow | 保留；后续可加 handler，但不删 |
| `backend/graph/builder.py` | LangGraph builder、phase、routing、visit guard、standard flow、node visit validation | agent nodes、app flow、Harness execution payload | 保留 |
| `backend/graph/state.py` | AgentState 类型定义 | graph/agents/tests | 保留 |
| `backend/harness/policy.py` | ToolGateway policy | `backend/tool_gateway.py`、tests | 保留 |
| `backend/harness/context_manager.py` | redaction/context strategy | execution builder/tests | 保留 |
| `backend/harness/execution_builder.py` | harness execution summary | `backend/app.py` execution payload/tests | 保留 |
| `backend/harness/security.py` | security helper | harness tests / future upload convergence | 保留 |
| `backend/harness/fallback_manager.py` | fallback helper | harness tests / future runtime | 保留 |
| `backend/tests/*.py` | 当前测试套件 | pytest | 不能删除 |

## 6. wrapper / compatibility 文件分析

### `backend/graph_runtime.py`（已完成）

当前状态：

```text
standard_flow() 和 validate_node_visits() 已合并到 backend/graph/builder.py。
backend/app.py、backend/harness/runtime.py、backend/harness/execution_builder.py、backend/tests/test_harness_runtime.py 已改为从 graph.builder 导入。
backend/graph_runtime.py 已删除。
```

它目前主要提供：

- `standard_flow(task_type)`
- `validate_node_visits(visited)`
- 从 `graph.builder` re-export `initial_phase` 等 graph 常量/路由能力

判断：该项已完成。后续不应重新创建 `backend/graph_runtime.py`。

### `backend/harness/runtime.py`

当前内容已经实化为 upload/chat runtime controller，不再只是 re-export。它不应删除。

建议：P0 中让它成为上传和聊天统一入口，负责初始化 state、调用 LangGraph、捕获 fallback、构建 execution payload，并让 `backend/app.py` 变薄。

### `backend/mcp_client/client_manager.py`

当前内容只是：

```python
from tool_gateway import ToolGateway

def create_tool_gateway(conn, task_id) -> ToolGateway:
    return ToolGateway(conn, task_id)
```

全局搜索没有发现主流程调用 `create_tool_gateway`。它属于兼容 facade。可以保留到下一轮，等 Harness Runtime 接管 ToolGateway 创建后再考虑删除。

### `backend/mcp_client/tool_invoker.py`

当前内容只是：

```python
from tool_gateway import ToolGateway

__all__ = ["ToolGateway"]
```

全局搜索没有发现主流程从它 import。它属于兼容 re-export。可以在下一轮确认没有外部脚本依赖后删除，但本轮不建议直接删。

## 7. legacy RAG 文件分析

### `backend/rag.py`

虽然文件名像旧版 RAG，但当前仍承担关键 fallback 和 note chunk 功能，不能删除。

当前被引用：

```text
backend/app.py: from rag import note_to_chunks, split_chunks
backend/vector_store.py: from rag import score_chunks
backend/adaptive_rag/hybrid_retriever.py: from rag import score_chunks
backend/tests/test_note_skill_note_index.py: from rag import note_to_chunks
```

当前关键函数：

- `split_chunks`
- `score_chunks`
- `note_to_chunks`
- `tokenize`
- `infer_section`

判断：不能删除。若要收敛，可后续把 `score_chunks` 移到 `backend/vector_store.py` 或 `backend/adaptive_rag/hybrid_retriever.py`，把 `note_to_chunks` 移到 `backend/note_skill.py` 或单独 note chunk helper，把 `split_chunks` 的调用逐步替换为 semantic chunker / note chunker。迁移完成并跑通 tests 后，才可删除。

### `backend/structured_retriever.py`

当前仍是 app.py 与 Adaptive RAG 之间的重要桥接层，也保留 legacy fallback 路径，不能删除。

当前被引用：

```text
backend/app.py: build_evidence_bundle, collect_structured_scope_chunks, rag_pipeline_summary, retrieve_structured_evidence
backend/adaptive_rag/adaptive_retriever.py: build_meta, collect_structured_scope_chunks
backend/adaptive_rag/hybrid_retriever.py: collect_structured_scope_chunks, extract_page_number, retrieve_figure, retrieve_page, retrieve_table
```

当前关键能力：

- 在 `RAG_ADAPTIVE_ENABLED` 时转到 `adaptive_rag.adaptive_retriever.adaptive_retrieve`
- 在关闭 adaptive RAG 时提供 legacy retrieval fallback
- 收集 paper/note/global scope chunks
- page/table/figure direct retrieval
- `build_evidence_bundle`
- `rag_pipeline_summary`
- legacy meta 构造和 rerank

判断：不能删除。它目前并非废弃文件，而是桥接层。后续只有在 app.py 和 adaptive_rag 都不再依赖其中函数，并且 legacy fallback 有替代实现后，才能删除或拆分。

### `backend/adaptive_rag/`

这是当前真实 RAG v2 实现，不是中间目录。内部文件互相引用，并且测试直接覆盖：

```text
backend/layout_parser.py -> adaptive_rag.abstract_detector
backend/structured_retriever.py -> adaptive_rag.adaptive_retriever
backend/tests/test_rag_*.py -> adaptive_rag.*
```

判断：全部保留。

## 8. 推荐删除路线

### Round 1：安全删除

目标：只删除无 import 的旧文件。

当前可选候选：

```text
backend/graph/checkpoint.py
```

但建议先确认它不是计划中的 checkpoint/state snapshot 预留功能。若确认不用，删除前验收：

```powershell
python -m pytest backend\tests -q
npm run build
```

本轮没有发现 `_old.py`、`_bak.py`、`legacy_*.py` 等明显可删文件。

### Round 2：合并 wrapper

目标：迁移 import，保留兼容测试，再删除 wrapper。

建议顺序：

1. 已完成：将 `backend/graph_runtime.py` 的 `standard_flow`、`validate_node_visits` 合并到 `backend/graph/builder.py`。
2. 已完成：修改 `backend/app.py`、`backend/harness/runtime.py`、`backend/harness/execution_builder.py`、`backend/tests/test_harness_runtime.py` 的 import。
3. 已完成：删除 `backend/graph_runtime.py`。
4. 下一步可选：确认外部没有使用 `backend/mcp_client/client_manager.py` 和 `backend/mcp_client/tool_invoker.py`。
5. 如果 Harness Runtime 已统一创建 ToolGateway，且 README/docs 不再把 `mcp_client` 作为当前结构入口，则删除 `backend/mcp_client/` 兼容 facade。

### Round 3：功能收敛

目标：等 Harness Runtime 接管后，再考虑移动或删除旧桥接文件。

建议顺序：

1. 实化 `backend/harness/runtime.py`，让上传和聊天统一进入 Harness Runtime。
2. 让 `backend/app.py` 变薄，只保留 FastAPI 参数校验和 response 返回。
3. 将直接数据库/文件/RAG 调用逐步收敛到 ToolGateway 和 MCP server 具名函数。
4. 为 `backend/rag.py` 的 `split_chunks`、`score_chunks`、`note_to_chunks` 找到明确归属并迁移 import。
5. 将 `backend/structured_retriever.py` 的 legacy fallback、scope chunk collection、page/table/figure direct retrieval 拆到更明确模块，或保留为正式桥接层并在 README 中说明。

## 9. 下一轮 Codex 删除任务 prompt

```text
请基于 docs/python_file_consolidation_audit.md 做 Python 文件收敛的第一轮实施，不要修改业务行为，不要删除 backend/tests/。

目标：
1. 不再处理 backend/graph_runtime.py；该 wrapper 已删除。
2. 不删除 backend/rag.py、backend/structured_retriever.py、backend/note_skill.py、backend/database.py、backend/schema.sql、backend/tool_gateway.py。
3. 不创建 backend/rag/、backend/skills/、backend/database/、frontend/src/api/、frontend/src/stores/。

执行步骤：
1. 重新运行 git status --short，确认工作区状态。
2. 重新运行 rg 检查以下文件的 import：
   - backend/graph/checkpoint.py
   - backend/harness/runtime.py
   - backend/mcp_client/client_manager.py
   - backend/mcp_client/tool_invoker.py
3. 如果 backend/graph/checkpoint.py 仍无任何 import，且确认不作为 checkpoint 预留能力使用，可以删除它。
4. 对 backend/mcp_client/client_manager.py 和 backend/mcp_client/tool_invoker.py 暂不删除，除非确认没有外部脚本依赖，并且 README/docs 不再把 mcp_client 作为当前结构入口。
5. 跑 python -m pytest backend\tests -q。

验收：
- python -m pytest backend\tests -q 通过。
- npm run build 通过。
- PDF upload、RAG retrieval、note generation、chat session、execution panel 行为不变。
- 最终说明删除了哪些文件、修改了哪些 import、哪些 wrapper 暂时保留。
```
