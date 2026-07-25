# 12 流式协议与前端状态

## 1. 前端分层

```text
Next.js Pages / Layouts
→ workspace 业务组件
→ core 领域 Hook、API、纯状态模型
→ LangGraph SDK + Gateway REST
```

主入口：

- `frontend/src/core/api/api-client.ts`
- `frontend/src/core/threads/hooks.ts::useThreadStream`
- `frontend/src/core/threads/hooks.ts::useThreadHistory`
- `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
- `frontend/src/components/workspace/messages/message-list.tsx`

## 2. 两类服务端协议

### LangGraph 兼容 API

用于：

- thread state/history；
- Run create/stream/wait/cancel/join；
- checkpoint execution。

### DeerFlow REST API

用于：

- branch；
- compact；
- regenerate prepare；
- token usage；
- uploads/artifacts；
- workspace changes；
- goals。

原则：图执行交给 SDK，产品特有能力使用 REST，不必强塞进 LangGraph 协议。

## 3. Stream Events

| 事件 | 数据 | UI 用途 |
|---|---|---|
| `metadata` | run/thread ID | 建立 Run 与更新列表 |
| `values` | 完整 ThreadState | title、todo、goal、artifact、恢复 |
| `messages` | message chunk + metadata | 逐 token、tool calls/results |
| `updates` | node/middleware writes | summarization、局部状态变化 |
| `custom` | task/retry 等业务事件 | Subagent 进度、重试提示 |
| `error` | 运行错误 | 解锁 UI、错误展示 |
| `end` | 流结束 | 完成 loading |

请求中的 `messages-tuple` 会映射为 Python LangGraph `messages`。

### `events` 边界

前端支持列表包含 `events`，但当前 Gateway Worker 会跳过，因为完整 callback events 需要不同的 `astream_events()` 管线。新增功能不能只看前端类型。

## 4. `useThreadStream()`

它组合：

- SDK `useStream()`；
- 历史消息；
- optimistic messages；
- attachments；
- send guard；
- regenerate；
- cache invalidation；
- custom Subagent events；
- summarization rescue；
- stop wrapper。

这不是单纯网络 Hook，而是前端聊天状态协调器。

## 5. 三个消息来源

```text
RunEvent 历史
+ SDK live messages/checkpoint
+ local optimistic messages
```

优先级通常是 live > history > optimistic。

ToolMessage 使用 `tool_call_id` 去重，因为历史与实时副本可能有不同 message ID，但语义上响应同一个 Tool call。

Visible message 优先于复用 ID 的 hidden control message。

## 6. Optimistic Human Message

发送后立即显示本地消息，但不能在第一个 AI chunk 到达时就删除。原因：`messages` 的 AI chunk 可能早于 `values` 中服务端 HumanMessage 到达。

正确条件是看到服务端 HumanMessage count 增加，再移除 optimistic 副本。

## 7. 新 Thread 竞态

浏览器先生成 UUID，但 SDK 暂不把它当已存在 Thread，避免 history 请求早于 Run create。

服务端创建成功后用原生 History API 更新 URL，保持当前 React/SDK store 不重挂载。

因此 `window.location.pathname` 与 `useParams()` 可能短暂不同步，代码不能盲信单一来源。

## 8. 历史加载

`useThreadHistory()`：

1. 获取 thread runs；
2. 从最新 Run 向前加载；
3. 分 run 请求 messages；
4. 使用 `before_seq` 分页；
5. 将 wrapper 的 `run_id` 附到 message；
6. 过滤不需要显示的 middleware messages。

为什么不只读 checkpoint：Summarization 会删除旧 active messages，完整可见历史保存在 RunEventStore。

## 9. Summarization Rescue Buffer

当后端先更新 live state、React 历史 state 尚未提交时，被压缩消息可能短暂从两个来源都消失。

解决：

- update event 同步写入 ref buffer；
- 异步 append 到历史 state；
- render 时叠加 buffer；
- 历史确认后清理。

这是跨两个状态源实现无闪烁投影的典型 generation bridge。

## 10. Subagent UI

两条通道：

- 普通 Message 协议提供 durable terminal status；
- custom SSE 提供实时 step timeline。

刷新后，SubtaskCard 展开时按 `run_id + task_id + after_seq` 从 events API 回填。

状态更新使用：

- pure `computeNextSubtask()`；
- `mergeSteps()`；
- `tasksRef.current` 防 async backfill 覆盖新 SSE 状态；
- terminal status 不可降级。

## 11. Human Input UI

Request 位于：

```text
ToolMessage.artifact.human_input
```

Response 是隐藏 HumanMessage：

```text
additional_kwargs.hide_from_ui = true
additional_kwargs.human_input_response = {...}
```

MessageList 从原始消息推导 answered/latest/open。Composer 在有 open request 时锁定，防普通消息绕过结构化 response metadata。

Pending 清理不仅看 Promise：若 dispatch 后 SSE 异步失败，新的 `thread.error` 也必须解锁卡片。

## 12. Goal 与 Compact 竞态

InputBox 对请求使用：

- AbortController；
- sequence number；
- captured thread ID；
- current controller identity。

线程切换时 abort；晚响应只有同时匹配 sequence/thread/controller 才能更新 UI。

`undefined` goal 表示服务端没提供，`null` 表示明确清除，不能混淆。

## 13. Stop

Stop 的真实时序可能是：

```text
本地 abort
→ fire-and-forget cancel
→ 后端 interrupted finalization
→ title/thread meta 更新
```

前端立即 invalidation，并延迟约 1.5 秒再次刷新，读取最终 title/status/token。

Cancel 若遇到“Run 已 success/error/interrupted”的 409，可视为幂等 no-op；若是“not active on this worker”，不能吞掉。

## 14. Reconnect

SDK 保存 resumable run ID。页面刷新后 join 前先 `runs.get()`：

- running：join；
- success/error/timeout/interrupted：短路并清理 reconnect key；
- 否则处理真实错误。

这是为避免 Run stream 已在结束后清理，客户端却永远等待。

## 15. Regenerate

前端先调用 prepare API 获取精确 input/checkpoint/metadata，再通过 SDK submit。

旧回答立即由 optimistic superseded set 隐藏；新 Run 成功后由 metadata 永久确认；提交失败则恢复旧回答。

## 16. Branch

Branch 创建新 Thread，不隐藏原回答。后端复制目标 checkpoint 并记录 lineage，前端导航新 Thread。

历史 turn 分支不复制当前 workspace，防未来文件泄漏。

## 17. TanStack Query 边界

Query 管理离散 REST state：

- thread lists；
- runs；
- metadata；
- token usage；
- artifact；
- workspace changes；
- uploads。

SDK 管理高频实时 state。不要把每个 SSE chunk 又同步进 Query，避免双重状态机。

## 18. 典型竞态模式

- in-flight ref：防双发；
- listener ref：避免 async callback 使用旧 props；
- generation token：拒绝旧请求响应；
- state ref：async merge 读取最新状态；
- optimistic overlay：临时本地事实；
- tombstone：regenerate 隐藏旧 Run；
- rescue buffer：跨 state source 无缝衔接；
- delayed invalidation：等待后端 finalization。

## 19. 常见坑

- 将 `events` 误认为已由 Gateway 支持。
- 忘记给历史 message 保留 `run_id`，导致 workspace/subtask 查询失效。
- Human input metadata 放错 sendMessage 参数。
- Raw fetch 在跨域部署未带 credentials/CSRF。
- 把 `write-file:` 草稿 URL 当正式 artifact。
- Run 未 finalization 就查询 workspace diff。
- 在 React render 中增加更多状态副作用。
- 仅靠 abort，不使用 sequence/thread ID 拒绝晚响应。

## 20. 面试题

### 1. 为什么 SSE state 不放 TanStack Query？

SDK 已管理 message delta、reconnect 和 stop；Query 更适合离散 REST state，二次同步会产生冲突状态机。

### 2. 为什么历史和 live 都需要？

Live 服务当前流，历史保存被 summarization 移出 checkpoint 的完整可见消息与 Run attribution。

### 3. Subagent 为什么需要 custom + ToolMessage？

Custom 提供实时进度，ToolMessage 提供持久终态和刷新恢复。

### 4. Stop 后为什么两次刷新？

第一次可能早于后端 title/token finalization，延迟刷新获取最终投影。

### 5. Regenerate 与 Branch 有何区别？

前者同 Thread 替代回答，后者复制 checkpoint 到新 Thread 保留两条时间线。
