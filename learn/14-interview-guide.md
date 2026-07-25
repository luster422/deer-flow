# 14 Agent 开发面试知识地图

## 1. 回答框架

每个架构题用四段式：

1. **原理**：定义与目标；
2. **实现**：DeerFlow 关键路径；
3. **权衡**：收益与代价；
4. **故障**：边界与错误场景。

不要只说“用了 LangGraph、Redis、微服务”，要解释数据和控制流。

## 2. Agent 基础

### Q1：什么是 Agent，与普通 Chain 有什么区别？

Agent 根据模型输出动态选择 Tool 和下一步，存在循环、状态与终止条件；普通 Chain 通常是预定义数据流。Agent 更灵活，但更难测试、控制成本和保证安全。

### Q2：ReAct 的核心是什么？

模型在推理、行动和观察之间循环。工程上应把 reasoning 与用户正文、tool call 与真实执行、观察与 ToolMessage 分离，不能让模型直接执行能力。

### Q3：Tool calling 如何工作？

模型返回 name/args/id，运行时进行授权、路由、校验和执行，再用 matching `tool_call_id` 的 ToolMessage 回填。

### Q4：为什么需要结构化协议？

自然语言不稳定。状态、错误、人工输入、Subagent、Goal 等需要 schema/version/ID，模型文本只用于语义表达。

## 3. LangChain / LangGraph

### Q5：`create_agent()` 与 LangGraph 的关系？

LangChain 高层工厂内部构建并编译 LangGraph，返回 CompiledStateGraph。

### Q6：Reducer 为什么重要？

并行节点可能写同一 channel，reducer 决定最终合并事实。错误 reducer 会导致数据丢失、状态降级或安全 invariant 破坏。

### Q7：Checkpointer 与 Store 区别？

Checkpointer 保存图执行状态和历史；Store 是通用 namespace KV。

### Q8：`recursion_limit` 是什么？

图 super-step 上限，不是 token、时间或单纯调用次数。

### Q9：`Command` 有什么作用？

统一表达 state update 与 goto/resume 等控制流，使 Tool/Node 能安全改变图状态。

### Q10：Interrupt 和 Human Input 新 Run 有何区别？

Interrupt 暂停原图并 resume 原节点；DeerFlow Web clarification 结束当前图，用隐藏 HumanMessage 开新 Run。

## 4. DeerFlow 架构

### Q11：DeerFlow 是官方 LangGraph Server 吗？

不是。Gateway 自行实现兼容 API，并内嵌运行同一个 Agent graph factory。

### Q12：Thread、Run、Checkpoint、Event 区别？

Thread 是长期会话；Run 是一次执行；Checkpoint 是图状态快照；Event 是过程投影。

### Q13：为什么 Gateway 内嵌 Runtime？

部署和认证统一、多个入口复用；代价是多 worker task ownership 和 HTTP/重工作负载耦合。

### Q14：为什么 Harness 不依赖 App？

保持 Agent 内核可嵌入和可发布，防 HTTP/产品层反向污染。

### Q15：Redis 是否解决多 worker？

只解决 StreamBridge 跨进程事件；取消、admission、finalizing 和 task ownership 仍需分布式控制。

## 5. Middleware 与上下文

### Q16：Middleware 顺序为什么关键？

Wrapper 内外层、反向 after_model、metadata 依赖和 tool pairing 都受顺序影响。

### Q17：ToolProgress 与 LoopDetection 区别？

前者看结果质量，后者看调用模式。

### Q18：为什么 Memory/summary 不是 SystemMessage？

它们是用户/模型派生的不可信数据，升权会增加持久化 prompt injection。

### Q19：Summary 和 Memory 区别？

Summary 是线程任务上下文，Memory 是跨线程用户事实。

### Q20：大 Tool output 怎么处理？

外置完整结果、给 preview 与读取路径；失败时有界截断，并处理历史大消息。

## 6. Tool、Skill、MCP

### Q21：Tool、Skill、MCP 区别？

执行能力、工作流知识、外部能力协议。

### Q22：为什么 deferred tools 需要执行前再次检查？

隐藏 schema 不是授权，模型可猜名字；必须两道门。

### Q23：MCP session 为什么含 user/thread？

Thread 保持状态连续，user 防租户间共享 Cookie/文件/会话。

### Q24：Skill `allowed-tools` 有什么边界？

当前是已启用 Skills 显式工具并集，不是当前激活 Skill 的严格临时权限。

### Q25：如何设计新 Tool？

明确 schema、授权、Sandbox、超时、幂等、副作用、错误、输出预算、secret、SSRF、审计和测试。

## 7. 安全

### Q26：为什么 Prompt 不能作为安全边界？

模型可能被注入、误解或不遵守；授权和限制必须由确定性代码执行。

### Q27：Guardrail 与 Sandbox 区别？

前者决定是否允许，后者限制执行影响范围。

### Q28：LocalSandbox 安全吗？

不构成 OS 隔离，生产不可信场景应使用容器/VM。

### Q29：如何传 request secret？

放 runtime context，经 live Skill 声明授权，以结构化 env 注入，不进入 prompt/args/command/checkpoint/trace。

### Q30：如何防 Prompt Injection？

角色降权、数据 envelope、能力最小化、执行授权、HITL、Agent 分权和 egress 控制；不是简单关键词过滤。

## 8. Subagent

### Q31：Subagent 是否完全独立？

推理图独立，常共享 workspace/sandbox 和父身份。

### Q32：为什么禁止递归委派？

控制并发、成本、取消和状态复杂度，防指数爆炸。

### Q33：Timeout 与 max turns 区别？

墙钟时间与图步骤预算；max turns 可携带 partial result。

### Q34：为什么取消不是硬中断？

Python async/thread 多为协作取消，阻塞同步操作需要自身 timeout 或进程级隔离。

### Q35：为什么 step 捕获不能只看最后消息？

同一 super-step 可追加多个 ToolMessages。

## 9. 持久化与一致性

### Q36：为什么 Checkpointer 不等于 RunStore？

前者保存图恢复状态，后者保存产品层执行元数据。

### Q37：为什么没有全局事务？

Checkpoint、SQL、Stream、文件、外部 tracing 跨不同系统；采用关键路径强约束和其他投影最终一致。

### Q38：原子文件替换解决多进程并发吗？

只防半写，不防 lost update。

### Q39：为什么 Postgres orphan recovery 更难？

多 worker 下 running row 可能仍有合法 owner，需要 lease/heartbeat/fencing。

### Q40：Workspace 为什么不能随 rollback？

它不在 LangGraph checkpoint 中；需要独立文件事务或快照系统。

## 10. Streaming 与前端

### Q41：为什么需要 values 和 messages？

前者同步完整 state，后者逐 token；二者用途不同。

### Q42：为什么历史消息单独加载？

Summarization 会缩短 active checkpoint，RunEventStore 保留完整可见历史和 Run attribution。

### Q43：Optimistic message 如何去重？

等待服务端对应 HumanMessage 真正出现；ToolMessage 用 tool_call_id 作为身份。

### Q44：Stop 后为什么延迟刷新？

后端还有 title/token/thread metadata finalization。

### Q45：Regenerate 与 Branch 区别？

同 Thread 替代 Run vs 新 Thread 时间线。

## 11. 可观测性与测试

### Q46：为什么不记录每个 token 到数据库？

频率和锁成本过高；实时流与长期事件分工。

### Q47：Tracing 为什么挂 graph root？

确保一个业务 Run 一个 root trace，内部节点为 child，避免重复 callback。

### Q48：Agent 如何测试？

纯函数、Middleware、fake graph、runtime、API contract、frontend E2E、最后 live eval 分层。

### Q49：为什么不能只测最终答案？

工具、状态、成本、安全和恢复可能都错误，但最终文本偶然正确。

### Q50：Agent Eval 指标有哪些？

任务成功、工具准确、步骤、成本、延迟、citation、安全、可恢复性和用户体验。

## 12. 系统设计题：设计企业知识 Agent

建议回答结构：

1. 身份与租户；
2. RAG/Tool/MCP 能力；
3. State 与 Memory；
4. Checkpoint 与 Run/Event；
5. Streaming 与 UI；
6. RBAC/ABAC 与 Sandbox；
7. Secret 与审计；
8. 并发、预算和超时；
9. Observability/Eval；
10. Multi-region 与 worker lease。

强调：只读检索 Agent 与执行写操作 Agent 可分权；高风险操作增加审批；文档内容是不可信数据。

## 13. 模拟面试评分

| 维度 | 优秀表现 |
|---|---|
| 概念准确 | 不混淆 Thread/Run/Checkpoint/Store |
| 源码证据 | 能说出关键类和路径 |
| 设计权衡 | 同时说明收益、代价与边界 |
| 并发意识 | 主动考虑竞态、取消和多 worker |
| 安全意识 | 不把 Prompt、Scanner、LocalSandbox 当强边界 |
| 数据意识 | 明确 authority、retention、consistency |
| 工程能力 | 能提出测试、监控和迁移方案 |
