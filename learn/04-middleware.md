# 04 Middleware 设计与执行顺序

## 1. 一句话心智模型

Middleware 是 DeerFlow 的 Agent 操作系统：它在不修改标准 ReAct 图的前提下控制输入、模型请求、工具授权、上下文、预算、错误、记忆和人工交互；**排列顺序本身就是系统行为与安全协议**。

## 2. Hook 模型

LangChain `AgentMiddleware` 常见 Hook：

| Hook | 执行时机 | 典型用途 |
|---|---|---|
| `before_agent` / `abefore_agent` | 整个 Agent turn 前 | 初始化 thread data、uploads、sandbox |
| `before_model` / `abefore_model` | 每次模型调用前 | 动态上下文、摘要、durable context |
| `after_model` / `aafter_model` | 模型返回后 | title、token、loop、safety、subagent limit |
| `wrap_model_call` / `awrap_model_call` | 包裹实际模型调用 | 输入清洗、重试、deferred schemas |
| `wrap_tool_call` / `awrap_tool_call` | 包裹工具执行 | guardrail、audit、read-before-write、错误处理 |

两个顺序规则必须牢记：

1. `wrap_*` 中列表靠前者通常是外层 wrapper。
2. `after_model` 常按注册顺序反向执行。

## 3. 当前 Lead Agent Middleware 顺序

### 共享运行时层

1. `InputSanitizationMiddleware`
2. `ToolOutputBudgetMiddleware`
3. `ThreadDataMiddleware`
4. `UploadsMiddleware`
5. `SandboxMiddleware`
6. `DanglingToolCallMiddleware`
7. `LLMErrorHandlingMiddleware`
8. `GuardrailMiddleware`，可选
9. `SandboxAuditMiddleware`
10. `ReadBeforeWriteMiddleware`，可选
11. `ToolProgressMiddleware`，可选
12. `ToolErrorHandlingMiddleware`

构建入口：`backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`

### Lead-only 层

13. `DynamicContextMiddleware`
14. `SkillActivationMiddleware`
15. `DurableContextMiddleware`
16. `DeerFlowSummarizationMiddleware`，可选
17. Todo Middleware，计划模式
18. `TokenUsageMiddleware`，可选
19. `TitleMiddleware`
20. `MemoryMiddleware`
21. `ViewImageMiddleware`，可选
22. `DeferredToolFilterMiddleware`，可选
23. `SystemMessageCoalescingMiddleware`
24. `SubagentLimitMiddleware`，可选
25. `LoopDetectionMiddleware`，可选
26. `TokenBudgetMiddleware`，可选
27. Custom Middlewares
28. `SafetyFinishReasonMiddleware`，可选
29. `ClarificationMiddleware`

构建入口：`backend/packages/harness/deerflow/agents/lead_agent/agent.py::build_middlewares`

## 4. 关键顺序约束

### InputSanitization 必须靠外

它要保证后续所有模型请求转换、内部重试和模型本身看到清洗后的消息。同时保留原始用户文本到受控 metadata，供 slash activation 等可信逻辑使用。

### ToolProgress 必须包裹 ToolErrorHandling

返回方向上，内层 `ToolErrorHandling` 先将结果标准化为 `deerflow_tool_meta`，外层 `ToolProgress` 才能依据结构化状态判断 no-results、rate-limit、auth、重复结果等。

```text
ToolProgress
  └─ ToolErrorHandling
       └─ Actual Tool
```

构建代码会检查该不变量，顺序错误直接报错。

### ReadBeforeWrite 必须更外层

未满足先读后写时，它应直接阻断，不执行实际工具，也不消耗 ToolProgress 的一次停滞计数。因为绕过了内层 ErrorHandling，它必须自行标准化阻断结果。

### DurableContext 必须在 Summarization 前

它先从消息中提取 Subagent 委派和 Skill 引用，再让摘要删除旧 ToolMessage。反过来会丢失结构化上下文。

### Safety 注册靠后但实际先处理

`after_model` 反向执行。Safety 需要先读取 provider finish reason 并清除可能被安全截断的 tool calls，再交给 LoopDetection 和 SubagentLimit，避免危险调用执行或误统计。

### Clarification 必须最后

它是 `ask_clarification` 的特殊终止器：不执行占位 Tool，而是生成 ToolMessage 和 `Command(goto=END)`。放置不当可能被其他 wrapper 改写或实际执行。

## 5. 输入与消息协议保护

### Input Sanitization

目标不是简单删除特殊字符，而是：

- 标记真实用户内容；
- 隔离 framework 注入文本；
- 保持原始文本供可信解析器使用；
- 防止后续 Middleware 误把动态上下文当用户命令。

### Dangling Tool Call

当取消或 provider 异常导致 `AIMessage.tool_calls` 没有对应 ToolMessage 时，严格 provider 会拒绝下一次请求。该 Middleware 补 synthetic ToolMessage，并保持：

```text
AIMessage(tool_calls) → ToolMessage(s) → 后续消息
```

### System Message Coalescing

部分 provider 要求 system message 必须位于开头且只有一个连续块。该 Middleware 只在模型请求层合并静态和动态 SystemMessage，不修改 checkpoint 原始结构。

## 6. 模型错误处理

`LLMErrorHandlingMiddleware` 负责：

- 识别 408/409/425/429/5xx；
- 指数退避；
- `Retry-After`；
- stream chunk timeout；
- circuit breaker；
- 发布 retry custom event；
- 最终生成可读 error fallback AIMessage。

为什么不直接抛异常：用户需要可理解错误，图也可能继续保存状态。

为什么 Worker 仍检查 marker：合法 AIMessage 会让图正常结束，但业务 Run 应是 `error` 而不是 `success`。

## 7. 工具错误与进度

### ToolErrorHandling

- 普通异常转 error ToolMessage，让模型尝试替代策略；
- 保留 `GraphBubbleUp`，因为它是 interrupt/pause 等图控制流；
- 给结果添加结构化 metadata；
- 为 task 和 skill read 添加专用字段。

### ToolProgress

按 `(thread, tool)` 跟踪结果质量：

- 可恢复错误：警告并允许改参数；
- transient/rate-limit：警告后可升级为 block；
- auth/config/internal：首次即 block；
- 高相似成功结果也可视为无进展。

### LoopDetection

观察调用模式而不是结果质量：

- 相同 tool call signature 重复；
- 同类工具调用频率过高；
- hard stop 时清除所有 tool calls，要求模型总结。

警告不能在 `after_model` 立即插入，否则会夹在 AI tool call 与 ToolMessage 之间。正确做法是先排队，在下一次 `wrap_model_call` 追加隐藏 HumanMessage。

## 8. 上下文 Middleware

### DynamicContext

- 当前日期：SystemMessage，框架权威数据；
- Memory：隐藏 HumanMessage，用户派生的不可信数据；
- 原始用户问题：保持 HumanMessage。

这种角色分离避免 Memory 内容被提升为 system authority。

### SkillActivation

解析严格 `/skill-name task`，验证 enabled、agent allowlist 和 canonical path，将 SKILL.md 作为当前请求隐藏上下文注入，并记录 audit。

### DurableContext

将 summary、delegation result、skill reference 投影给模型：

- 固定 authority contract 放入 SystemMessage；
- 实际动态数据放入隐藏 HumanMessage。

### Summarization

模型调用前判断 token/message trigger，将旧历史更新为 `summary_text` 并保留近期窗口。摘要模型加 no-stream tag，防止其 token 被前端误当主回答。

## 9. 预算与安全

### TokenUsage vs TokenBudget

- Usage：观测、归因和统计；
- Budget：控制本 Run 的 warning/hard stop。

两者不能合并，因为控制策略和计费事实职责不同。

### Guardrail vs SandboxAudit

- Guardrail：所有工具的身份/角色/参数授权，可插拔 provider；
- SandboxAudit：专门检查 Bash command 的风险模式；
- 二者都不是 Sandbox 隔离的替代品。

### Safety Finish Reason

Provider 因 content filter/refusal 终止时，可能留下截断 tool calls。Middleware 删除它们，避免执行不完整或未经安全确认的调用。

## 10. Summarization 细节

自动压缩：

1. 补稳定消息 ID；
2. 将已有 `summary_text` 纳入 token 估算；
3. 选择 cutoff；
4. 保护动态日期/Memory 及其用户消息 peers；
5. 运行 before-summarization hook；
6. 生成递增摘要；
7. 返回 `RemoveMessage(ALL) + preserved messages + summary_text`。

Memory hook 会在消息被删除前排队提取长期事实。

手工 `/compact` 复用同一实现，只更新 `messages` 与 `summary_text` channel，并与 Run admission/goal 写共享 thread lock。

## 11. 新 Middleware 设计检查表

- 应使用哪个 hook？
- 同步与异步版本是否都正确？
- 是否读取或写入 ThreadState？
- 状态是否需要跨 Run？
- 是否改变消息顺序或 ID？
- 是否可能破坏 tool-call pairing？
- 是否依赖其他 Middleware 的 metadata？
- 应位于依赖者外层还是内层？
- `after_model` 反向顺序是否符合预期？
- 异常应该 fail-open 还是 fail-closed？
- 对 Gateway 每 Run 重建 graph 和 Embedded Client 缓存 graph，内部状态语义是否一致？
- 多 worker 时是否需要共享状态？
- 是否会进入 tracing 和 token 统计？

## 12. 面试题

### 1. Middleware 顺序为什么不是实现细节？

因为 wrapper 内外层、反向 `after_model`、消息 pairing 和 metadata 依赖会直接改变授权、错误、工具执行与模型输入。

### 2. ToolProgress 与 LoopDetection 的区别？

前者看工具结果是否产生新信息，后者看模型是否重复调用模式；一个可 block 单工具，另一个可终止整轮工具执行。

### 3. 为什么 `GraphBubbleUp` 必须重抛？

它是 LangGraph 控制流，不是业务异常；吞掉会破坏 interrupt/resume。

### 4. 为什么 Memory 用隐藏 HumanMessage？

Memory 来自用户与模型提取，属于不可信数据；使用 SystemMessage 会产生权限提升。

### 5. 为什么循环警告延迟到下一次模型请求？

避免在 AI tool calls 和对应 ToolMessages 之间插入其他角色消息，破坏 provider 协议。
