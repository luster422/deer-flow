# 15 实战实验

建议在独立分支或临时练习目录完成，不要直接改生产配置。每个实验都应记录：目标、假设、步骤、观察、源码证据、结论。

## Lab 1：最小 LangChain Tool Agent

目标：理解 Message 与 Tool calling。

任务：

1. 使用 fake chat model；
2. 定义一个加法 Tool；
3. 用 `create_agent()` 创建 Agent；
4. 打印 HumanMessage → AI tool call → ToolMessage → AI answer；
5. 比较 Tool 返回字符串、ToolMessage、Command。

验收：能解释模型没有直接执行函数。

## Lab 2：Reducer 与并行工具

目标：理解 LangGraph 并发 state。

任务：定义 `artifacts/audit_events/cost` 三个 channel，对应有序去重、append、sum reducer；让多个工具并行写入。

验收：删除 reducer 后能观察或解释并发写冲突。

## Lab 3：Checkpoint 时间旅行

目标：理解 thread 和 checkpoint。

任务：

1. 使用 InMemorySaver；
2. 同 thread 运行两轮；
3. 列出历史 checkpoint；
4. 从第一轮 checkpoint 运行不同输入；
5. 比较两条时间线。

## Lab 4：Interrupt 与 Clarification 对比

实现真正 `interrupt()`：

1. 节点请求审批；
2. 查看 `__interrupt__`；
3. `Command(resume=answer)`；
4. 再分析 DeerFlow `goto=END + hidden HumanMessage`。

验收：能说明两种 HITL 的状态和 UI 取舍。

## Lab 5：Middleware 顺序实验

编写：

- input sanitizer；
- model retry wrapper；
- tool error wrapper；
- after_model safety cleanup。

交换顺序并记录调用栈和消息变化。

验收：画出 wrap 进入/返回顺序和 after_model 反向顺序。

## Lab 6：三种 Stream Mode 消费器

- `values`：只显示 title/todo/artifact；
- `messages`：按 ID 累积文本；
- `custom`：显示进度。

验收：不从 values 重复渲染已由 messages 输出的 AI 文本。

## Lab 7：安全 Tool 设计

设计一个只读 SQL Tool：

- 参数化 SELECT；
- 禁止多语句；
- 禁止系统表；
- 最多 100 行；
- 5 秒 timeout；
- Analyst role Guardrail；
- secret 不进入 Tool args；
- 大输出外置。

交付：接口 schema、威胁模型、错误协议和测试表。

## Lab 8：Request Secret 泄露测试

使用唯一测试 token，触发 Skill Bash：

检查 token 不出现在：

- Prompt；
- Tool args；
- command；
- output；
- run config API；
- checkpoint；
- RunEvent；
- logs/tracing。

验收：Sandbox 内脚本能读取，所有其他平面不可见。

## Lab 9：Skill 包安全审计

构造包含：

- `../` 路径；
- symlink；
- `.env`；
- `curl | bash`；
- prompt override；
- executable magic；
- nested archive。

记录 preflight/native/LLM scanner 各层的处理。

## Lab 10：MCP Stateful Session

设计一个浏览器 MCP：

- 同 user/thread 复用；
- 不同 user 隔离；
- screenshot 写 thread workspace；
- 返回虚拟路径；
- 配置变更清理 session；
- OAuth 自动刷新。

验收：解释 owner task 和 AnyIO cancel scope。

## Lab 11：Subagent 并发

让 Lead 一次产生 4 个 task calls，配置允许 4，观察 scheduler 同时执行数量和第四个任务延迟。

验收：区分模型调用上限、scheduler capacity、provider/sandbox capacity。

## Lab 12：First-terminal-wins

构造 timeout 后仍晚到 completed 的 fake Subagent。

断言最终仍是 timed out，result/status 不被覆盖。

## Lab 13：Max Turns Partial Result

让 Subagent 先产生一段有效分析，再耗尽 recursion limit。

断言：

- status 是 max_turns_reached；
- result brief 存在；
- error 存在；
- Lead 可复用结果。

## Lab 14：Memory Debounce 与 Frozen Snapshot

1. debounce 窗口内提交多次更新；
2. 验证只处理最新完整 conversation；
3. 当前 Thread 首次注入 Memory；
4. 后台更新 Memory；
5. 当前 Thread 继续、新 Thread 开始；
6. 比较两者 Memory。

## Lab 15：Memory Lost Update

两个进程同时读取同一 memory.json 并写不同 fact。

验收：证明 atomic replace 不防 lost update，并提出 CAS/数据库方案。

## Lab 16：Run 持久化失败

让 RunStore 首次 put 抛异常。

断言：

- API 不返回成功；
- RunManager 内存索引回滚；
- thread index 无残留；
- 没有后台 task 启动。

## Lab 17：Orphan Recovery

SQLite 模式：启动 Run 后强杀 Gateway，再启动。

检查：

- Run 变 error；
- Thread 状态更新；
- retained stream 收到 END；
- UI 不永久 loading。

## Lab 18：Journal 非原子故障

让 RunEventStore flush 失败，但 Checkpointer 正常。

观察：

- 会话可继续；
- checkpoint 完整；
- 历史审计缺失；
- Run 是否仍成功。

用于理解“状态权威 vs 可观测投影”。

## Lab 19：Summarization 前端竞态

模拟顺序：

1. live messages 缩短；
2. render；
3. history append；
4. render；
5. history 确认；
6. prune rescue buffer。

断言每一帧可见消息不丢失。

## Lab 20：Reconnect

测试 Run 状态：

- running；
- success；
- interrupted；
- 404；
- store-only 且当前 worker 无 stream。

验收：说明 join、短路、报错和回退策略。

## Lab 21：Regenerate 与 Branch

对同一回答分别：

- regenerate；
- branch latest turn；
- branch historical turn。

观察 Run lineage、Thread ID、旧回答可见性和 workspace clone mode。

## Lab 22：Token 与 Cost

构造 Lead + 两个不同模型 Subagent，并模拟 cache read tokens。

验收：

- Run total；
- caller buckets；
- per-model buckets；
- cache-aware cost；
- unpriced model 为 null。

## Lab 23：Trace 跨边界

携带 `X-Trace-Id` 触发：

- Lead Run；
- Subagent；
- Memory Timer。

检查响应 Header、日志、Langfuse metadata 和后台线程是否一致。

## Lab 24：阻塞 I/O

在测试分支故意把同步文件读取放入 async path，验证 runtime gate；再使用 `asyncio.to_thread` 修复。

验收：解释为什么“函数声明 async”不代表不会阻塞。

## 综合项目：企业研究 Agent

功能要求：

- LangGraph state；
- 两个只读 Tool 和一个审批后写 Tool；
- Checkpointer；
- Streaming UI；
- Subagent；
- Memory；
- Guardrail；
- Sandbox；
- request secret；
- Run/Event persistence；
- tracing/token/cost；
- unit/integration/E2E/eval。

设计评审必须回答：

- 权威状态在哪里？
- 哪些数据最终一致？
- 如何多租户隔离？
- 如何取消和恢复？
- 如何防 prompt injection 与工具越权？
- 如何控制成本？
- 多 worker 如何做 ownership 与 lease？
