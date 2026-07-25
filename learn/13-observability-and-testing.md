# 13 可观测性与测试

## 1. 可观测性四平面

| 平面 | 主要组件 | 用途 |
|---|---|---|
| Run 元数据 | RunStore/RunRow | 状态、模型、token、错误、时间 |
| 事件历史 | RunJournal/RunEventStore | 消息、工具、Middleware、Subagent |
| 实时流 | StreamBridge/SSE | 用户实时体验与重连 |
| 外部追踪 | LangSmith/Langfuse/trace context | span、调用树、跨系统关联 |

Checkpoint 是状态恢复面，也常用于排障，但不是传统 observability store。

## 2. RunJournal

`RunJournal` 是 LangChain CallbackHandler，负责：

- run start/end/error；
- LLM request/response；
- visible messages；
- tool result reconciliation；
- middleware audit；
- latency；
- token usage；
- first human / last AI convenience fields；
- batch 写 RunEventStore。

它不逐 token 写数据库。逐 token 由 StreamBridge 负责，避免存储爆炸和锁竞争。

## 3. RunEvent Sequence

`seq` 在同一 Thread 内严格递增，不是每 Run 从 1 开始。原因是前端要构造跨 Run 的会话时间线。

PostgreSQL 使用 thread-scoped advisory transaction lock 后分配连续 seq；数据库唯一约束 `(thread_id, seq)` 是最终保护。

查询单 Run 时 seq 有空洞是正常的。

## 4. Subagent Events

Custom live events 转换为持久：

- `subagent.start`；
- `subagent.step`；
- `subagent.end`。

按 category 隔离，不混入普通消息 feed。Step 使用 batch flush，换取写入效率，但 crash 时最后小批事件可能丢失。

## 5. Token Usage

RunJournal 从 provider usage metadata 采集：

- input；
- output；
- total；
- cache read；
- model；
- caller attribution。

Subagent 使用独立 collector，再合并父 Run。计费应优先使用 per-model breakdown，因为 Lead、Subagent 和 Middleware 可能使用不同模型。

### Token 的三个不同用途

- Usage：事实与计费；
- Budget：运行控制；
- Context token estimate：Summarization 触发。

三者可能使用不同来源和精度，不能混为一个数字。

## 6. Cost

Console 根据模型 pricing 计算：

```text
uncached input cost
+ cache-hit input cost
+ output cost
```

未配置价格返回 null，而不是 0。Legacy Run 缺 per-model 数据时只能退回主模型和 Run totals，准确度较低。

## 7. Trace ID

需要区分：

- `run_id`：业务 Run 主键；
- Subagent short trace：执行日志辅助 ID；
- `deerflow_trace_id`：HTTP/日志/Langfuse correlation ID；
- Langfuse/LangSmith 自己的 trace identity。

HTTP `TraceMiddleware` 读取或生成 `X-Trace-Id`，绑定 ContextVar，并在 SSE response start 时返回同一个 Header。

## 8. ContextVar 跨边界

ContextVar 通常随 asyncio task 传播，但不会自动跨：

- 原生线程；
- `threading.Timer`；
- 自建 event loop；
- 某些 executor 边界。

DeerFlow 显式使用：

- `copy_context()`；
- context 数据字段；
- `request_trace_context()`；
- enqueue 时捕获 user/trace。

新增后台任务时必须检查身份和 trace 是否仍然正确。

## 9. Tracing Callback 为什么挂 Graph Root

Graph root callback 可形成：

```text
一个业务 Run Trace
  ├─ graph nodes
  ├─ model calls
  └─ tool calls
```

若 model 自己又 attach tracing，可能出现重复 root、双重 token 和错误 session/user metadata。Graph 内模型通常关闭 model-level tracing，由根回调统一管理。

Subagent 通常形成同一 session 下的独立 trace，而非父 trace 内严格 child span；需要结合 thread session、request trace 和 task ID 关联。

## 10. 日志与敏感信息

可观测性数据同样是泄露面：

- Tool args 可能含用户数据；
- Bash command 可能含字面 secret；
- messages 可能含隐私；
- Run config 必须脱敏；
- request secret 只记录名称，不记录值；
- retention、访问控制和导出策略必须明确。

## 11. Agent 测试金字塔

### 纯函数测试

最稳定、最快：

- reducers；
- message parsing；
- step merge；
- status transition；
- pricing；
- path normalization；
- policy filtering。

### Middleware 单元测试

使用 fake request/handler 验证：

- 顺序；
- state update；
- error conversion；
- fail-open/closed；
- message pairing；
- async/sync parity。

### Graph 测试

使用 fake model/tools/checkpointer：

- tool loop；
- parallel reducers；
- recursion limit；
- interrupt/resume；
- checkpoint branch；
- stream modes。

### Runtime 集成测试

验证：

- RunManager admission；
- cancel/rollback/finalizing；
- StreamBridge；
- Journal flush；
- orphan recovery；
- persistence failure。

### API/协议测试

验证：

- Pydantic schemas；
- LangGraph SDK compatibility；
- CSRF/auth；
- SSE frames；
- history pagination；
- cross-language contracts。

### Frontend 单元/E2E

验证：

- optimistic merge；
- reconnect；
- stop；
- summarization race；
- human input pending；
- task backfill；
- branch/regenerate。

### Live/Eval

最后才使用真实模型评估：

- 任务成功率；
- 工具选择；
- citation；
- safety；
- latency/cost；
- regression dataset。

## 12. 为什么 Agent 测试不能只断言最终文本

最终文本具有随机性，且会掩盖：

- 调错工具；
- 多调了很多次；
- 权限绕过；
- token 暴涨；
- 状态未持久；
- UI 无法重连；
- 事件缺失；
- 文件写错目录。

应同时断言：

- state；
- tool call sequence；
- structured metadata；
- Run status；
- events；
- token/cost；
- artifacts/workspace；
- security policy；
- stream ordering。

## 13. 阻塞 I/O

异步 Agent Runtime 中，任何同步文件、网络、数据库或 subprocess 操作都可能阻塞 event loop。

DeerFlow 使用：

- `asyncio.to_thread`；
- async Sandbox acquire；
- dedicated file I/O executor；
- Blockbuster runtime tests；
- AST scanner。

测试必须执行真实路径；静态扫描和运行时测试互补。

## 14. 故障排查方法

### UI 卡在 loading

依次查：

1. Run status；
2. reconnect key；
3. StreamBridge 是否有 END；
4. Gateway 是否 join 终态 Run；
5. worker 是否卡在 finalizing；
6. SSE proxy buffering/timeout。

### Run success 但历史缺消息

查：

1. Checkpoint 是否完整；
2. Journal flush；
3. RunEventStore；
4. category/filter；
5. hidden message policy。

### Token 不准

查：

1. provider usage metadata；
2. callback 是否重复；
3. source run ID 去重；
4. Subagent usage 回收；
5. final completion write。

### 取消失败

查：

1. Run 是否 store-only；
2. 当前 worker 是否 owner；
3. task 是否在不可取消同步调用；
4. abort event 是否检查；
5. finalizing 是否仍进行。

## 15. 面试题

### 1. 为什么 Journal 不保存每个 token？

实时 token 是高频传输数据，写数据库成本过高；StreamBridge 处理 delta，Journal 保存消息级事实。

### 2. 为什么 Trace callback 要挂 graph root？

保证一个 Run 一个 root trace，节点、模型、工具成为 child，避免重复追踪和计数。

### 3. 如何测试 LLM 系统的确定性部分？

把 reducer、协议、policy、state transition、pricing 和解析器提取为纯函数，用 fake model/tool 验证图和 runtime。

### 4. 为什么成功率不是唯一 Eval 指标？

还需关注成本、延迟、调用次数、安全、可恢复性、citation 和用户体验。

### 5. ContextVar 在后台线程为什么危险？

不会自动传播，可能使用默认或错误用户，导致跨租户数据访问和 trace 断裂。
