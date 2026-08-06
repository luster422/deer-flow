# 16 源码阅读地图

## 1. 阅读原则

- 先沿主调用链，再深入横切模块。
- 先读类型和纯函数，再读大型 Hook/Worker。
- 同时追踪 happy path、异常、取消和 finalization。
- 遇到 `store` 先确认具体接口类型。
- 遇到消息先确认 role、ID、hidden、tool_call_id 和 additional kwargs。
- 遇到 context 先确认 ThreadState、runtime context、configurable 还是 metadata。

## 2. 第一遍：30 分钟建立全局地图

1. `AGENTS.md`
2. `backend/AGENTS.md`
3. `frontend/AGENTS.md`
4. `backend/langgraph.json`
5. `backend/app/gateway/app.py`
6. `backend/packages/harness/deerflow/agents/thread_state.py`
7. `backend/packages/harness/deerflow/agents/lead_agent/agent.py`
8. `backend/packages/harness/deerflow/runtime/runs/worker.py`
9. `frontend/src/core/threads/hooks.ts`

目标：知道服务、状态、Agent factory、Worker、Frontend hook 分别在哪里。

## 3. 第二遍：请求主链路

按顺序读：

1. `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
2. `frontend/src/components/workspace/chats/use-thread-chat.ts`
3. `frontend/src/core/threads/hooks.ts::useThreadStream`
4. `frontend/src/core/api/api-client.ts`
5. `docker/nginx/nginx.local.conf`
6. `backend/app/gateway/routers/thread_runs.py`
7. `backend/app/gateway/services.py::start_run`
8. `backend/packages/harness/deerflow/runtime/runs/manager.py`
9. `backend/packages/harness/deerflow/runtime/runs/worker.py::run_agent`
10. `backend/app/gateway/services.py::sse_consumer`

目标：手动画出端到端时序。

## 4. 第三遍：Agent 装配

1. `agents/lead_agent/agent.py::_make_lead_agent`
2. `models/factory.py`
3. `tools/tools.py::get_available_tools`
4. `agents/lead_agent/prompt.py::apply_prompt_template`
5. `agents/lead_agent/agent.py::build_middlewares`
6. `agents/middlewares/tool_error_handling_middleware.py::_build_runtime_middlewares`
7. `agents/thread_state.py`

目标：回答模型、工具、Prompt、Middleware 和 State 从哪里来。

## 5. 第四遍：Middleware 深读顺序

建议按依赖关系：

1. `input_sanitization_middleware.py`
2. `dynamic_context_middleware.py`
3. `durable_context_middleware.py`
4. `summarization_middleware.py`
5. `system_message_coalescing_middleware.py`
6. `llm_error_handling_middleware.py`
7. `tool_result_meta.py`
8. `tool_error_handling_middleware.py`
9. `tool_progress_middleware.py`
10. `loop_detection_middleware.py`
11. `read_before_write_middleware.py`
12. `guardrails/middleware.py`
13. `safety_finish_reason_middleware.py`
14. `clarification_middleware.py`

目标：画出 wrapper 内外层和 after_model 逆序。

## 6. 第五遍：LangGraph 状态与历史

1. `runtime/checkpointer/async_provider.py`
2. `runtime/store/async_provider.py`
3. `app/gateway/routers/threads.py`
4. `runtime/context_compaction.py`
5. `runtime/goal.py`
6. regenerate prepare in `routers/thread_runs.py`
7. branch in `routers/threads.py`
8. interrupt serialization tests

目标：区分 branch、regenerate、compact、rollback、interrupt。

## 7. 第六遍：Tools / Skills / MCP

### Tools

1. `tools/tools.py`
2. `tools/builtins/present_file_tool.py`
3. `tools/builtins/clarification_tool.py`
4. `sandbox/tools.py`
5. `agents/middlewares/tool_output_budget_middleware.py`

### Skills

1. `skills/parser.py`
2. `skills/storage/skill_storage.py`
3. `skills/storage/user_scoped_skill_storage.py`
4. `skills/slash.py`
5. `agents/middlewares/skill_activation_middleware.py`
6. `skills/catalog.py`
7. `skills/describe.py`
8. `skills/installer.py`
9. `skills/skillscan/orchestrator.py`

### MCP

1. `mcp/client.py`
2. `mcp/cache.py`
3. `mcp/session_pool.py`
4. `mcp/tools.py`
5. `mcp/oauth.py`
6. `tools/builtins/tool_search.py`
7. `agents/middlewares/deferred_tool_filter_middleware.py`

目标：回答能力如何发现、授权、延迟暴露和隔离。

## 8. 第七遍：Sandbox 与安全

1. `sandbox/sandbox.py`
2. `sandbox/sandbox_provider.py`
3. `sandbox/middleware.py`
4. `sandbox/local/local_sandbox.py`
5. `sandbox/local/local_sandbox_provider.py`
6. `community/aio_sandbox/`
7. `community/boxlite/`
8. `sandbox/env_policy.py`
9. `agents/middlewares/read_before_write_middleware.py`
10. `agents/middlewares/sandbox_audit_middleware.py`
11. `guardrails/`
12. `community/url_safety.py`

目标：完成威胁模型和多租户检查表。

## 9. 第八遍：Subagent

1. `tools/builtins/task_tool.py`
2. `subagents/config.py`
3. `subagents/registry.py`
4. `subagents/executor.py`
5. `subagents/step_events.py`
6. `subagents/status_contract.py`
7. `contracts/subagent_status_contract.json`
8. `runtime/runs/worker.py::_SubagentEventBuffer`
9. `frontend/src/core/tasks/*`

目标：画出 task 从 Tool call 到历史卡片的完整协议。

## 10. 第九遍：Memory 与 Persistence

### Memory

1. `agents/memory/message_processing.py`
2. `agents/middlewares/memory_middleware.py`
3. `agents/memory/queue.py`
4. `agents/memory/updater.py`
5. `agents/memory/storage.py`
6. `agents/middlewares/dynamic_context_middleware.py`

### Persistence

1. `persistence/run/model.py`
2. `persistence/run/sql.py`
3. `runtime/events/store/base.py`
4. `runtime/events/store/db.py`
5. `persistence/thread_meta/`
6. `persistence/bootstrap.py`
7. `persistence/migrations/`

目标：画出五类存储职责图。

### Knowledge / RAG

1. `docs/plans/2026-07-31-rag-design.md`
2. `deerflow/knowledge/ports.py` / `types.py` / `config.py`
3. `deerflow/knowledge/chunking/markdown.py`
4. `deerflow/knowledge/retrieval/local.py`
5. `deerflow/knowledge/manager.py` / `tools.py`
6. `deerflow/persistence/knowledge/*` + `migrations/versions/0008_knowledge_bases.py`
7. `app/knowledge/{runtime,ingestion,storage}.py`
8. `app/gateway/routers/knowledge_bases.py`
9. `frontend/src/core/knowledge/*` + `app/workspace/knowledge-bases/page.tsx`
10. `frontend/src/components/workspace/knowledge-base-selector.tsx`

目标：说清入库、绑定、混合检索与 `knowledge_search` 的权限边界。详见 `23-knowledge-rag.md`。

## 11. 第十遍：Streaming Frontend

1. `frontend/src/core/threads/types.ts`
2. `frontend/src/core/api/stream-mode.ts`
3. `frontend/src/core/api/api-client.ts`
4. `frontend/src/core/threads/hooks.ts::mergeMessages`
5. `frontend/src/core/threads/hooks.ts::useThreadHistory`
6. `frontend/src/core/messages/utils.ts`
7. `frontend/src/components/workspace/messages/message-list.tsx`
8. `frontend/src/core/messages/human-input.ts`
9. `frontend/src/core/tasks/*`
10. `frontend/src/core/workspace-changes/*`
11. `frontend/src/components/workspace/input-box.tsx`

目标：解释 optimistic、history、live、rescue buffer 和 Query cache 的边界。

## 12. 第十一遍：Observability 与测试

1. `runtime/journal.py`
2. `runtime/events/`
3. `runtime/stream_bridge/`
4. `trace_context.py`
5. `tracing/factory.py`
6. `tracing/metadata.py`
7. `app/gateway/trace_middleware.py`
8. `app/gateway/routers/console.py`
9. `backend/tests/` 对应模块测试
10. `frontend/tests/unit/` 与 `frontend/tests/e2e/`

目标：从一次失败 Run 找到所有证据平面。

## 13. 第十二遍：SDK 设计

1. `packages/harness/deerflow/client.py::DeerFlowClient.__init__`
2. `packages/harness/deerflow/client.py::_get_runnable_config`
3. `packages/harness/deerflow/client.py::_ensure_agent`
4. `packages/harness/deerflow/client.py::stream`
5. `packages/harness/deerflow/client.py::_stream_without_trace_context`
6. `packages/harness/deerflow/client.py::chat`
7. `runtime/runs/worker.py::run_agent`
8. `runtime/serialization.py`
9. `runtime/stream_bridge/`
10. `backend/docs/STREAMING.md`
11. `backend/tests/test_client.py`
12. `backend/tests/test_client_langfuse_metadata.py`

目标：解释 LangGraph 远程 SDK 与嵌入式 `DeerFlowClient` 在哪里共享 Agent 内核、在哪里因调用边界不同而分叉，并能为新 SDK 方法设计兼容契约和测试。

## 14. 第十三遍：Gateway 专题

1. `backend/app/gateway/app.py::create_app`
2. `backend/app/gateway/app.py::lifespan`
3. `backend/app/gateway/deps.py::langgraph_runtime`
4. `backend/app/gateway/deps.py::get_run_context`
5. `backend/app/gateway/auth_middleware.py`
6. `backend/app/gateway/csrf_middleware.py`
7. `backend/app/gateway/authz.py`
8. `backend/app/gateway/internal_auth.py`
9. `backend/app/gateway/routers/thread_runs.py`
10. `backend/app/gateway/routers/runs.py`
11. `backend/app/gateway/services.py::normalize_input`
12. `backend/app/gateway/services.py::build_run_config`
13. `backend/app/gateway/services.py::start_run`
14. `backend/app/gateway/services.py::sse_consumer`
15. `backend/app/gateway/routers/threads.py`
16. `backend/packages/harness/deerflow/runtime/runs/manager.py`
17. `backend/packages/harness/deerflow/runtime/runs/worker.py`

目标：说明 Gateway 的应用装配、安全边界、API 平面、Run 准入、基础设施生命周期与多 Worker 约束，并能判断新逻辑应属于 Gateway 还是 Harness。

## 15. 符号搜索清单

建议重点搜索：

```text
make_lead_agent
create_agent
ThreadState
build_middlewares
start_run
run_agent
RunManager
RunJournal
StreamBridge
Command
interrupt
summary_text
goal_thread_lock
task_tool
SubagentExecutor
get_available_tools
DeferredToolFilterMiddleware
SkillActivationMiddleware
SandboxProvider
MemoryUpdateQueue
mergeMessages
useThreadStream
DeerFlowClient
StreamEvent
_stream_without_trace_context
create_app
langgraph_runtime
normalize_input
build_run_config
AuthMiddleware
CSRFMiddleware
```

## 16. 源码笔记模板

每读一个模块记录：

```text
模块：
入口：
输入：
输出：
持久状态：
临时状态：
并发模型：
错误策略：
安全边界：
可观测性：
关键测试：
设计取舍：
仍有疑问：
```

## 17. 最终自测

不打开文档，尝试从空白画出：

1. 服务拓扑；
2. 单 Run 时序；
3. Thread/Run/Checkpoint/Event 数据关系；
4. Middleware 顺序；
5. Tool/Skill/MCP/Sandbox 能力链；
6. Subagent 状态机；
7. Memory 更新链；
8. Frontend 三源消息合并；
9. 多 worker 缺口；
10. Agent 测试金字塔；
11. 远程 SDK 与嵌入式 Client 的共享内核和分叉边界；
12. Gateway 的应用生命周期、安全边界、API 平面和 Run 控制面。

如果其中任何一张图无法解释“为什么”，回到对应专题和源码重新验证。
