# DeerFlow Agent 开发学习手册

这套文档以当前仓库源码为教材，目标不是复述产品说明，而是帮助你从 DeerFlow 建立一套可迁移到其他 Agent 项目的工程知识体系：能看懂架构、能追踪一次运行、能解释 LangChain/LangGraph 抽象、能设计工具与多 Agent、能分析安全和一致性，并能在面试中讲清楚设计取舍。

## 学习目标

完成本手册后，你应当能够：

1. 从浏览器输入开始，完整讲出请求经过 Nginx、Gateway、RunManager、LangGraph、StreamBridge 再回到前端的链路。
2. 区分 LangChain、LangGraph 与 DeerFlow 自有抽象，不把 `Thread`、`Run`、`Checkpoint`、`RunEvent`、`Store` 混为一谈。
3. 解释 Lead Agent、Middleware、ThreadState、Tool、Skill、MCP、Sandbox、Subagent、Memory 的职责与协作方式。
4. 解释流式输出、取消、重连、分支、重生成、上下文压缩和人工输入为何需要状态机与并发控制。
5. 识别 Agent 工程中的提示词注入、工具越权、秘密泄漏、路径逃逸、循环调用、阻塞 I/O 和多实例一致性风险。
6. 独立完成一个带状态、工具、持久化、流式 UI、可观测性和测试的 Agent 功能。
7. 回答本手册中的核心面试题，并用 DeerFlow 源码说明答案，而不是只背概念。

## 文档目录

| 阶段 | 文档 | 核心问题 |
|---|---|---|
| 导航 | [00 学习目标与路线](00-learning-goal-and-roadmap.md) | 如何学、如何验收？ |
| 架构 | [01 系统架构](01-system-architecture.md) | DeerFlow 为什么这样分层？ |
| 架构 | [02 一次请求的生命周期](02-request-lifecycle.md) | 一条消息到底经历了什么？ |
| Agent | [03 Agent 核心设计](03-agent-core.md) | Lead Agent 如何被装配并运行？ |
| Agent | [04 Middleware 设计](04-middleware.md) | 中间件顺序为什么是系统行为？ |
| 框架 | [05 LangChain 基础](05-langchain-foundations.md) | Message、Model、Tool、Runnable 是什么？ |
| 框架 | [06 LangGraph 运行时](06-langgraph-runtime.md) | State、Reducer、Checkpoint、Command 如何协作？ |
| 上下文 | [07 状态与上下文工程](07-state-and-context-engineering.md) | 什么应该持久化，什么不应该？ |
| 能力 | [08 Tools、Skills 与 MCP](08-tools-skills-mcp.md) | Agent 能力如何发现、授权和执行？ |
| 安全 | [09 Sandbox 与安全](09-sandbox-and-security.md) | 如何隔离不可信执行？ |
| 多 Agent | [10 Subagent 与任务委派](10-subagents.md) | 多 Agent 如何并发、回收结果和控制预算？ |
| 数据 | [11 Memory 与持久化](11-memory-and-persistence.md) | 长期记忆、图状态与业务数据有何区别？ |
| 全栈 | [12 流式协议与前端状态](12-streaming-and-frontend.md) | SSE、历史、乐观状态如何合并？ |
| 工程 | [13 可观测性与测试](13-observability-and-testing.md) | 如何定位问题并验证 Agent？ |
| 面试 | [14 面试知识地图](14-interview-guide.md) | 高频问题如何形成结构化答案？ |
| 实践 | [15 实战实验](15-practice-labs.md) | 如何把理解变成可运行能力？ |
| 导航 | [16 源码阅读地图](16-source-reading-map.md) | 从哪些文件开始读最有效？ |
| SDK | [17 SDK 设计](17-sdk-design.md) | 远程 LangGraph SDK 与嵌入式 Client 如何分工？ |
| Gateway | [18 Gateway 设计](18-gateway-design.md) | API 边界、运行控制面与生命周期如何组织？ |
| 后端 | [19 完整后端模块架构](19-backend-module-architecture.md) | Provider、Usage、Runtime、数据与应用模块如何完整划分？ |
| 上下文 | [20 提示词与上下文工程](20-prompt-engineering.md) | Prompt、动态上下文、Tool Schema 与硬约束如何协作？ |
| 后端 | [21 Provider 设计模式](21-provider-design-pattern.md) | 可替换能力、配置解析、生命周期与错误契约如何设计？ |
| 取舍 | [22 官方 Server 与嵌入式运行时](22-langgraph-server-vs-embedded-runtime.md) | 相对原版 LangChain/LangGraph，DeerFlow 保留了什么、改了什么？ |

## 推荐学习顺序

### 路线 A：第一次接触 Agent 开发

按 `00 → 01 → 19 → 21 → 05 → 06 → 03 → 07 → 20 → 18 → 02 → 22 → 08 → 10 → 11 → 12 → 17 → 13 → 15` 学习。先建立系统和后端模块地图，再深入 Provider 边界，然后理解框架概念、提示词与上下文分层、Gateway 控制面、与官方 Server 的取舍，以及生产级能力和 SDK 接入边界。

### 路线 B：已有 LangChain/LangGraph 经验

按 `01 → 19 → 21 → 02 → 22 → 18 → 03 → 04 → 07 → 20 → 10 → 11 → 12 → 17 → 09 → 13` 学习。先掌握后端静态模块和 Provider 边界，再对照官方 Server 与嵌入式运行时的取舍，关注 Gateway 控制面、DeerFlow 的生产化封装、上下文运行时、远程/嵌入式接入。

### 路线 C：准备面试

先快速阅读 `01、19、21、02、22、18、03、06、07、20、08、10、11、12、17`，再完成 `14` 中的问题；回答时使用“概念 → DeerFlow 实现 → 设计取舍 → 故障场景”四段式。

### 路线 D：准备参与项目开发

先阅读 `16` 和 `19`，分别建立源码阅读顺序与模块所有权地图；新增或修改可替换实现时阅读 `21`，涉及 Agent 行为、上下文注入或模型可见 Tools 时继续阅读 `20`，再根据改动模块选择其他专题文档。修改代码时同时核对仓库根目录、`backend/AGENTS.md` 或 `frontend/AGENTS.md` 中的开发约束。

## 每章建议学习法

每章都尽量按以下结构组织：

1. **先回答核心问题**：用一句话建立心智模型。
2. **理解通用概念**：不局限于 DeerFlow。
3. **映射到源码**：定位关键类、函数和路径。
4. **画出调用链或状态机**：从静态结构走向运行时理解。
5. **分析设计取舍**：说明为什么没有采用更简单的方案。
6. **复盘故障模式**：理解复杂代码解决的真实问题。
7. **回答面试题**：训练准确、分层的表达。
8. **完成练习**：通过运行、断点、日志或测试验证理解。

## 文档版本说明

- 内容基于当前工作区源码整理，而不是只依据项目介绍文档。
- 源码不断演进，文档中的函数位置可能变化；应优先使用符号名和相对路径搜索。
- 本手册会明确区分“当前源码行为”“兼容接口声明”和“可改进方向”。例如前端允许 `events` stream mode，并不代表当前 Gateway 已完整实现该模式。
- 文档中的安全机制多数属于纵深防御的一层；任何单项机制都不应被误认为完整安全边界。
