# 05 LangChain 基础

## 1. LangChain 在 DeerFlow 中负责什么

LangChain 提供高层 Agent 抽象：

- 消息对象；
- ChatModel；
- Tool；
- RunnableConfig；
- Callback；
- AgentMiddleware；
- `create_agent()`。

LangGraph 则提供底层状态图运行时。DeerFlow 使用前者描述 Agent 能力，使用后者获得状态、持久化和流式执行。

## 2. 消息模型

### HumanMessage

表示用户输入，也可用于注入“用户派生但不可信”的隐藏上下文。常见 metadata：

- `hide_from_ui`；
- files；
- human input response；
- goal continuation；
- original user content marker。

### AIMessage

表示模型输出，可以包含：

- 文本；
- tool calls；
- usage metadata；
- reasoning；
- provider response metadata。

### ToolMessage

工具执行结果，必须通过 `tool_call_id` 对应 AIMessage 中的调用。DeerFlow 还使用：

- `status`；
- `artifact`；
- `additional_kwargs.deerflow_tool_meta`；
- subagent status/result；
- human input request。

### SystemMessage

框架权威规则。DeerFlow 谨慎控制哪些动态数据可以获得 system role；日期可以，Memory/summary/subagent result 通常不可以。

## 3. Tool Calling 不是函数直接执行

标准协议：

```text
模型看到工具 schemas
→ AIMessage.tool_calls(name, args, id)
→ Agent Runtime 按 name 路由并执行
→ 生成 ToolMessage(tool_call_id=id)
→ 模型看到结果并继续
```

模型只“请求调用”，实际权限、参数校验、执行、超时和审计都在运行时。

### Tool 返回类型

- 字符串/对象：框架包装成 ToolMessage；
- ToolMessage：工具精确控制结果；
- `Command`：同时更新 state、添加消息或改变图跳转。

### ToolRuntime

DeerFlow Tool 可从 runtime 获得：

- `state`；
- `context`；
- `config`；
- store；
- tool call ID。

不要把安全身份作为普通模型参数传入 Tool args；应来自受信 runtime context。

## 4. ChatModel

`BaseChatModel` 接收消息并返回 AIMessage/Chunk。DeerFlow 的模型 factory 处理：

- provider 类反射；
- model name；
- API 参数；
- thinking；
- reasoning effort；
- vision；
- OpenAI Responses API；
- vLLM 特殊 reasoning 字段；
- tracing callbacks。

### 模型抽象的价值

- Agent 不依赖具体 provider；
- 测试可使用 fake model；
- 中间件可以统一包裹模型调用；
- 配置可动态选择模型。

### 抽象泄漏

不同 provider 对 system message、tool call、reasoning、usage 和 safety finish reason 的支持不同。DeerFlow 通过 provider adapter 与 Middleware 修补，但不能假设完全一致。

## 5. Runnable 与 RunnableConfig

Runnable 是统一可调用/可流式/可批处理抽象。`RunnableConfig` 控制一次执行，而不是保存业务状态。

常见字段：

- `configurable`：thread/checkpoint 与兼容参数；
- `context`：运行时依赖；
- `recursion_limit`；
- `callbacks`；
- `metadata`；
- `tags`；
- `run_name`。

### 为什么不能把所有东西放 configurable

它与 checkpoint 寻址和部分持久化路径相关。Request secret、临时 token、journal 等不应进入长期配置；应放 runtime context，并在 Run record 持久化前脱敏。

## 6. Callback

Callback 用于观察执行：

- chain start/end/error；
- model start/end；
- tool start/end；
- token usage；
- tracing。

DeerFlow 的 `RunJournal` 是 CallbackHandler，将执行过程投影到 RunEventStore。

### Callback 不是业务状态

Callback 可能失败或延迟，不应成为图状态唯一来源。Checkpoint 和 state reducer 才决定 Agent 可恢复事实。

## 7. AgentMiddleware

Middleware 是对模型和工具调用的可组合拦截器。常见职责：

- 修改模型请求；
- 过滤工具 schemas；
- 重试；
- 工具授权；
- 结果标准化；
- 状态更新；
- 安全和预算。

与 Web Middleware 不同，它参与 Agent 图内部每一轮模型/工具循环。

## 8. `create_agent()`

概念参数：

```python
create_agent(
    model=model,
    tools=tools,
    middleware=middlewares,
    system_prompt=system_prompt,
    state_schema=ThreadState,
)
```

结果是编译后的 LangGraph，而不是普通 Python while 循环。它提供模型节点、工具节点和路由，DeerFlow 再注入 checkpointer/store。

## 9. 普通 Chain、ReAct 与 Agent Graph

### 普通 Chain

适合固定流程：分类、抽取、改写、单次 RAG。优点是简单和可预测，缺点是不具备自主工具循环。

### 手写 ReAct

```text
while not done:
  response = model(messages, tools)
  if tool_calls:
    execute tools
  else:
    return response
```

适合教学和极简系统，但很快需要自己实现状态、并发、持久化、取消、流式和恢复。

### LangGraph Agent

适合长会话、工具、多步骤、并行、checkpoint、interrupt、分支、streaming 和生产控制。

## 10. 结构化输出与错误

Agent 工程不要只依赖自然语言协议。DeerFlow 的例子：

- Tool 结果使用 `deerflow_tool_meta`；
- Subagent 使用 status contract；
- Human input 使用版本化 artifact；
- Goal evaluator 返回 typed blocker；
- Memory LLM 输出经过 JSON 解析和确定性校验。

原则：

> 模型负责语义判断，程序负责 schema、权限、边界和上限。

## 11. Token 与 Streaming

模型可以返回完整 AIMessage，也可以返回 AIMessageChunk。消费流时需要：

- 按 message ID 累积 delta；
- 区分正文、reasoning、tool call chunk；
- 避免从 values 再重复渲染同一 AI 文本；
- 最终从 usage metadata 统计 token。

## 12. 常见面试题

### 1. Tool calling 与 function execution 有什么区别？

模型只产生结构化意图；运行时负责真正执行和安全控制。

### 2. 为什么使用 LangChain Message，而不是 `{role, content}`？

标准 Message 还携带 ID、tool calls、chunks、usage、artifact 和 provider metadata，是 Agent 协议对象。

### 3. Callback 和 Middleware 有何区别？

Callback 主要观察生命周期；Middleware 可以改变模型请求、工具执行和 state，属于控制面。

### 4. `RunnableConfig` 是 state 吗？

不是。它描述一次运行的配置、上下文和观测信息；业务事实应进入 state 或专用存储。

### 5. 为什么 Agent 错误常转成 ToolMessage，而不是抛出？

让模型获知可恢复错误并选择替代方案；不可恢复或控制流异常仍应终止/重抛。

## 13. 练习

1. 用 fake model 和一个 `@tool` 创建最小 Agent。
2. 打印 HumanMessage、AIMessage、ToolMessage 的序列化结构。
3. 让 Tool 分别返回字符串、ToolMessage 和 Command，观察 state 差异。
4. 编写一个 `wrap_tool_call` Middleware，把异常转成结构化错误。
5. 同时挂 Callback 和 Middleware，记录二者调用顺序。
