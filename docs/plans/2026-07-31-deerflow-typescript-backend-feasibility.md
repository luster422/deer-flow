# DeerFlow TypeScript 后端可行性与实施方案

> 状态：提案  
> 日期：2026-07-31  
> 目标技术栈：TypeScript、NestJS、LangChain.js、LangGraph.js  
> 范围：Gateway 到 Harness，不包含 Frontend、Nginx、TUI 及外围接入服务

## 1. 结论

使用 TypeScript 和 NestJS 实现 DeerFlow 的后端核心是可行的。建议将项目定位为“兼容 DeerFlow 核心协议和行为的新实现”，而不是逐文件翻译 Python 代码。

技术可行性高，主要依据如下：

- NestJS 能覆盖 Gateway 的 REST、鉴权、生命周期、依赖注入、OpenAPI 和 SSE 能力。
- `@langchain/langgraph` 已提供 TypeScript 图运行时、状态 reducer、interrupt、stream 和 checkpoint 能力。
- LangChain.js 已覆盖主流模型、工具调用和消息抽象。
- MCP 官方 TypeScript SDK 成熟，MCP 不构成迁移障碍。
- PostgreSQL checkpointer 和 Redis Streams 能组成可横向扩展的运行与事件基础设施。
- DeerFlow 已有跨语言 JSON contract，可直接作为 TS 实现的兼容性测试输入。

真正的工程风险集中在以下方面：

1. Python 与 JavaScript 的 Agent middleware API 并非逐项等价。
2. 当前 DeerFlow 的 `RunManager + run_agent + StreamBridge` 包含大量并发、取消、回滚和最终化语义，不能简化成 Controller 中直接调用 `graph.stream()`。
3. Python checkpoint 的序列化内容不应假设可被 TypeScript 直接读取。
4. 生产沙箱必须依赖容器或远端执行环境，Node.js `vm` 不是安全边界。
5. 当前 Python 后端有约 30 个有顺序要求的 middleware。完整行为对齐会显著大于基础 Agent PoC。

建议先用 1 至 2 周完成技术验证；验证通过后，2 名有经验的工程师约 12 至 16 周可以交付可部署的核心 Beta。单人实现预计需要 5 至 7 个月。达到当前 Python 后端的大部分细节能力，预计需要 9 至 15 人月。

## 2. 项目边界

### 2.1 包含范围

本方案中的“Gateway 到 Harness”包括：

- NestJS Gateway
  - REST API
  - LangGraph 兼容的 threads、runs、assistants API
  - SSE 流式响应
  - 输入校验、鉴权接口、请求上下文和错误映射
- Run Runtime
  - Run 创建、排队、执行、取消、超时、回滚和最终化
  - 同一 thread 的并发控制
  - StreamBridge
  - Run event journal
  - Checkpoint 和 thread state
- Harness
  - Lead Agent
  - Middleware pipeline
  - 模型工厂
  - 内置工具、MCP 工具和 Skills
  - Sandbox 抽象和本地/容器实现
  - Subagent 委派
  - Memory、summarization、title 和 token usage
- 数据层
  - PostgreSQL
  - LangGraph checkpointer
  - runs、run_events、threads_meta、agents 等业务表
  - Redis Streams，用于多实例流式事件
- 可观测性
  - 结构化日志
  - OpenTelemetry 接口
  - run、thread、trace ID 关联

### 2.2 明确排除

首个项目不包含：

- Web Frontend
- Nginx
- TUI 或嵌入式 CLI 客户端
- Feishu、Slack、Telegram、Discord、DingTalk 等 IM Channel
- GitHub Webhook 接入
- Scheduler 和 scheduled tasks
- Provisioner 服务和 Kubernetes 控制面
- Browser Live WebSocket
- 面向运营人员的 Console UI

以下能力不是首版阻塞项，可在核心 Beta 后追加：

- Knowledge Base / RAG
- 完整 OAuth/OIDC 和细粒度 RBAC
- Feedback API
- 多种第三方 tracing provider 的全部兼容逻辑
- Python 版所有 community tool
- BoxLite、E2B、AIO Sandbox 等全部 provider

### 2.3 首版产品假设

- 先支持单租户或 `user_id=default` 的无鉴权模式。
- 第一持久化目标只支持 PostgreSQL，不同时维护 SQLite 方言。
- 开发模式可使用内存 StreamBridge；生产模式使用 Redis Streams。
- 先兼容现有 HTTP/SSE JSON 契约，不承诺 Python 内部类、包路径或 checkpoint 二进制兼容。
- 外部调用直接访问 Gateway，例如 `http://localhost:8001/api/...`，不依赖 Nginx 路径重写。

## 3. 兼容目标

兼容性按优先级分为三层。

| 层级 | 目标 | 要求 |
| --- | --- | --- |
| P0 | Wire compatibility | 路径、HTTP 状态码、请求/响应 JSON、SSE event 名称和主要字段兼容 |
| P1 | Behavioral compatibility | thread checkpoint、run 状态、取消、同线程冲突、tool call、interrupt 行为兼容 |
| P2 | Operational compatibility | 多实例恢复、Redis bridge、租约、审计、完整中间件和性能行为兼容 |

不把以下内容作为兼容目标：

- Python import path
- Pydantic model 的内部表示
- Python pickle 或 LangChain Python 对象序列化
- 与 Python Gateway 同时写入同一组 checkpoint 表
- 未公开的函数和类签名

现有仓库中的下列 contract 应直接复制到 TS 测试套件中消费，而不是另写一套：

- `contracts/run_event_stream_contract.json`
- `contracts/subagent_status_contract.json`
- `contracts/slash_skill_contract.json`
- `contracts/skill_review/*.schema.json`

## 4. 架构决策

### 4.1 总体结构

```text
HTTP Client
    |
    v
NestJS Gateway
    |  Controller / Guard / DTO / Exception Filter
    v
Application Runtime
    |  RunManager / RunWorker / StreamBridge / Journal
    v
Harness
    |  Lead Agent / Middleware / Tools / MCP / Skills / Subagents
    v
LangGraph.js + LangChain.js
    |
    +--> Model Providers
    +--> PostgreSQL Checkpointer
    +--> Sandbox Provider
```

必须保持单向依赖：

```text
apps/gateway -> packages/runtime -> packages/harness
                                      |
                                      v
                              packages/contracts

packages/harness -X-> apps/gateway
packages/harness -X-> @nestjs/*
```

Harness 是可独立发布和测试的 TypeScript 包。NestJS 只作为组合根，不进入 Agent 核心代码。

### 4.2 建议目录

```text
deer-flow-ts/
├── apps/
│   └── gateway/
│       ├── src/main.ts
│       ├── src/app.module.ts
│       └── src/modules/
│           ├── health/
│           ├── models/
│           ├── assistants/
│           ├── threads/
│           ├── runs/
│           ├── agents/
│           ├── skills/
│           ├── mcp/
│           ├── uploads/
│           └── artifacts/
├── packages/
│   ├── contracts/       # Zod schema、DTO、SSE 和 event contract
│   ├── config/          # YAML、环境变量解析、热加载边界
│   ├── persistence/     # Drizzle schema、migration、repository
│   ├── runtime/         # RunManager、RunWorker、StreamBridge、Journal
│   ├── harness/         # Agent、state、middleware、prompt
│   ├── tools/           # builtin、MCP、tool registry
│   ├── sandbox/         # provider 接口和实现
│   ├── skills/          # discovery、parser、policy
│   ├── subagents/       # registry、executor、task tool
│   └── observability/   # logging、metrics、tracing
├── contracts/           # 从 DeerFlow 上游同步的 JSON contract
├── test/
│   ├── contract/
│   ├── integration/
│   └── e2e/
├── pnpm-workspace.yaml
└── tsconfig.base.json
```

建议使用 pnpm workspace 和 TypeScript project references。首版不需要引入 Nx；当包数量、缓存和发布流程确实需要时再增加。

### 4.3 NestJS 选择

- NestJS 11
- `@nestjs/platform-fastify`
- `@nestjs/swagger`
- 全局 validation pipe，但 DTO 的核心 schema 使用 Zod 维护
- 全局 exception filter 统一映射 `400/401/403/404/409/422/500`
- SSE route 使用 Fastify raw response，显式控制 flush、disconnect 和 backpressure
- `OnApplicationBootstrap` 和 `BeforeApplicationShutdown` 管理数据库、Redis、MCP client、sandbox 和后台 worker

Controller 只负责协议转换。Run 创建、取消和等待等逻辑必须放在 application service/runtime 中，不能绑定到 HTTP request 生命周期。

## 5. 技术选型

截至 2026-07-31，npm 可获得的相关版本包括：

| 能力 | 建议包 | 已验证可用版本 |
| --- | --- | --- |
| Gateway | `@nestjs/core` | `11.1.28` |
| Agent graph | `@langchain/langgraph` | `1.4.8` |
| Checkpoint core | `@langchain/langgraph-checkpoint` | `1.1.3` |
| PostgreSQL saver | `@langchain/langgraph-checkpoint-postgres` | `1.0.4` |
| MCP | `@modelcontextprotocol/sdk` | `1.30.0` |
| ORM/query | `drizzle-orm` | `0.45.2` |

版本号只用于证明当前生态可用。项目创建时应使用 lockfile 固定经过验证的精确版本，不应自动追随 minor 更新。

其他建议依赖：

- Node.js 22 或更高 LTS
- TypeScript strict mode
- PostgreSQL 16+
- Redis 7+
- Zod
- `yaml`
- `pg`
- `ioredis`
- Pino
- Vitest
- Supertest 或 Fastify inject
- Testcontainers
- ESLint + Prettier

数据库推荐 Drizzle 加显式 SQL migration。原因是 run ownership 和 active-run 约束需要 partial unique index、事务锁和数据库特定 SQL，完全依赖 ORM 自动迁移会隐藏关键并发语义。

## 6. Gateway 模块设计

### 6.1 核心模块

| Nest module | 职责 |
| --- | --- |
| `ConfigModule` | 加载、校验和刷新配置，区分热加载字段与重启字段 |
| `ModelsModule` | 暴露模型列表和能力，不返回 API key |
| `AssistantsModule` | LangGraph assistants 兼容查询和 schema |
| `ThreadsModule` | thread CRUD、state、history、compact |
| `RunsModule` | create、stream、wait、join、cancel、events、messages |
| `AgentsModule` | 自定义 agent 配置、prompt、tool group、skill allowlist |
| `SkillsModule` | skill 发现、启停、内容读取和安全校验 |
| `McpModule` | MCP server 配置、连接测试、工具刷新 |
| `UploadsModule` | thread 级上传、列表、删除、大小限制 |
| `ArtifactsModule` | 安全读取 outputs/artifacts，处理 MIME 和 range |
| `RuntimeModule` | 组装 RunManager、worker、checkpointer、bridge、journal |

### 6.2 首版 API 面

首版至少实现：

```text
GET    /health

GET    /api/models
GET    /api/models/:name

POST   /api/assistants/search
GET    /api/assistants/:id
GET    /api/assistants/:id/graph
GET    /api/assistants/:id/schemas

POST   /api/threads
POST   /api/threads/search
GET    /api/threads/:threadId
PATCH  /api/threads/:threadId
DELETE /api/threads/:threadId
GET    /api/threads/:threadId/state
POST   /api/threads/:threadId/state
POST   /api/threads/:threadId/history

POST   /api/threads/:threadId/runs
POST   /api/threads/:threadId/runs/stream
POST   /api/threads/:threadId/runs/wait
GET    /api/threads/:threadId/runs
GET    /api/threads/:threadId/runs/:runId
POST   /api/threads/:threadId/runs/:runId/cancel
GET    /api/threads/:threadId/runs/:runId/join
GET    /api/threads/:threadId/runs/:runId/stream
GET    /api/threads/:threadId/runs/:runId/events
GET    /api/threads/:threadId/messages

POST   /api/runs/stream
POST   /api/runs/wait

GET    /api/mcp
PUT    /api/mcp
GET    /api/skills
POST   /api/skills/:name/toggle
GET    /api/agents
POST   /api/agents
PUT    /api/agents/:name
DELETE /api/agents/:name

POST   /api/threads/:threadId/uploads
GET    /api/threads/:threadId/uploads/list
DELETE /api/threads/:threadId/uploads/:filename
GET    /api/threads/:threadId/artifacts/*path
```

没有 Nginx 时不需要同时维护 `/api/langgraph/*`。如果将来需要与现有前端零配置连接，可以在 NestJS 内添加 `/api/langgraph` alias；alias 必须转发到同一个 Controller/use case，不能复制业务逻辑。

### 6.3 输入信任边界

Gateway 必须从外部输入中移除服务器拥有的字段，例如：

- `is_internal`
- `authz_attributes`
- `channel_user_id`
- `original_user_content`
- 隐藏上下文 marker
- 内部 checkpoint mode
- middleware 的 secret context token

可由客户端设置的 context 字段必须使用 allowlist，例如：

- `model_name`
- `thinking_enabled`
- `reasoning_effort`
- `is_plan_mode`
- `subagent_enabled`
- `max_concurrent_subagents`
- `max_total_subagents`
- `agent_name`

任何会提高权限或改变交互安全边界的字段必须由服务端产生。

## 7. Run Runtime

### 7.1 为什么需要独立 Runtime

一次 run 不等于一次 HTTP 请求。客户端可以断开 SSE，但 run 可能继续；客户端也可以重新 join、取消或查询结果。因此需要独立的运行记录和后台执行对象。

```text
POST /runs/stream
    |
    v
validate request and principal
    |
    v
RunManager.admit()
    |-- enforce thread concurrency strategy
    |-- persist pending run
    |-- capture rollback point when needed
    v
RunWorker.start()
    |-- pending -> running
    |-- build graph and runtime context
    |-- stream graph events to StreamBridge
    |-- persist journal events
    |-- finalize title, usage and workspace changes
    v
success | error | timeout | interrupted
    |
    v
publish END and retain stream for late subscribers
```

### 7.2 状态机

```text
pending -> running -> success
                   -> error
                   -> timeout
                   -> interrupted

pending ----------> interrupted
pending ----------> error
```

状态更新必须带条件，例如 `WHERE status IN ('pending', 'running')`，避免已完成 run 被延迟回调降级。

### 7.3 同线程并发

支持现有三种策略：

| 策略 | 行为 |
| --- | --- |
| `reject` | thread 已有 active run 时返回 409 |
| `interrupt` | 中断旧 run，保留旧 run 已写入 checkpoint 的进度，然后启动新 run |
| `rollback` | 中断旧 run，恢复旧 run 开始前 checkpoint，然后启动新 run |

不能只靠进程内 mutex 保证唯一 active run。PostgreSQL 应使用 partial unique index：

```sql
CREATE UNIQUE INDEX uq_runs_thread_active
ON runs(thread_id)
WHERE status IN ('pending', 'running');
```

应用内检查只是快速失败路径，唯一索引才是并发仲裁者。

### 7.4 取消机制

- 单实例：每个本地 run 绑定 `AbortController`。
- LangGraph/model/tool 调用必须传递 `AbortSignal`。
- 子进程工具收到取消后先发送 `SIGTERM`，超时后再终止容器内进程。
- 多实例：run 记录保存 `owner_worker_id` 和 lease；取消请求通过 Redis control channel 通知 owner。
- owner 已失联且 lease 过期时，其他 worker 可以将 run 标记为 error/interrupted，但不能假装继续一个无法恢复的 JavaScript 调用栈。

### 7.5 SSE 和 StreamBridge

保持现有 frame 形状：

```text
event: messages-tuple
data: [{...message chunk...}, {...metadata...}]
id: 1740000000000-0

```

必须支持：

- event 名称：`values`、`messages-tuple`、`updates`、`debug`、`tasks`、`checkpoints`、`custom`、`error`、`end`
- subgraph namespace：`values|<namespace>`，不能把 subagent snapshot 当作 root `values`
- heartbeat comment 或内部 heartbeat frame
- `Content-Location: /api/threads/{threadId}/runs/{runId}`
- 客户端断开后的 `cancel` 或 `continue` 策略
- 有界队列和 backpressure
- 迟到 subscriber 的短期事件保留

实现建议：

- 开发：`MemoryStreamBridge`，使用 async iterable 和有界 ring buffer。
- 生产：`RedisStreamBridge`，使用 `XADD`、`XREAD BLOCK`、stream ID 和 TTL。
- SSE 的 `id` 直接使用 Redis stream ID。
- `Last-Event-ID` 用于断线续读，但不把它宣传为无限期 resumable stream；保留窗口外应返回明确冲突或从当前点加入。

## 8. Harness 设计

### 8.1 Agent 构建策略

优先使用 LangChain.js 的 `createAgent` 和 middleware 能力承载标准 model-tool loop，同时在 DeerFlow 包内定义自己的 middleware 接口和顺序测试。这样上层不会直接依赖 LangChain.js 某一版本的 hook 细节。

第 1 周必须完成一个 spike，验证下列行为：

- model token 和 tool-call argument delta 能逐块输出
- 一个 tool call 可被 middleware 修改、拒绝和包装错误
- `beforeModel` 可以动态过滤 model-visible tool schema
- interrupt 可以产生可恢复 checkpoint
- `AbortSignal` 能中断模型和工具路径
- subgraph stream 保留 namespace

如果 `createAgent` 无法提供必要 hook，则 Harness 内部改为显式 `StateGraph`：

```text
prepare -> model -> route
                    |-- tools -> model
                    |-- interrupt -> END
                    `-- finalize -> END
```

该 fallback 只改变 Harness 内部，不改变 Gateway、Runtime 或 contracts。

### 8.2 State

使用 LangGraph.js Annotation/reducer 定义 `ThreadState`，至少包含：

```ts
interface ThreadState {
  messages: BaseMessage[];
  sandbox?: { sandboxId?: string };
  threadData?: {
    workspacePath?: string;
    uploadsPath?: string;
    outputsPath?: string;
  };
  title?: string;
  artifacts: string[];
  todos?: TodoItem[];
  goal?: GoalState;
  uploadedFiles?: UploadedFile[];
  viewedImages: Record<string, ViewedImageData>;
  promoted?: { catalogHash: string; names: string[] };
  delegations: DelegationEntry[];
  skillContext: SkillEntry[];
  summaryText?: string;
}
```

Reducer 语义要通过 fixture 锁定，特别是：

- messages 使用 LangGraph 标准 message reducer。
- artifacts 合并、去重并保序。
- sandbox 只允许幂等写入同一 ID，不同 ID 必须报错。
- promoted 以 catalog hash 隔离，catalog 改变时替换旧值。
- delegation 同 ID 取最新，但 terminal 状态不能退回 running。
- skill context 按 path 去重并限制数量。
- viewed image 只持久化 metadata，不持久化 base64。

### 8.3 Middleware 接口

建议在 Harness 中定义稳定接口：

```ts
interface DeerFlowMiddleware {
  name: string;
  beforeAgent?(ctx: AgentContext, state: ThreadState): Promise<StatePatch | void>;
  beforeModel?(ctx: ModelCallContext, next: ModelHandler): Promise<ModelResult>;
  afterModel?(ctx: ModelResultContext): Promise<ModelResult | StatePatch | void>;
  wrapToolCall?(ctx: ToolCallContext, next: ToolHandler): Promise<ToolResult>;
  afterAgent?(ctx: AgentContext, state: ThreadState): Promise<StatePatch | void>;
}
```

中间件顺序是行为契约，不能依赖 Nest provider discovery 顺序。使用显式数组构建，并为完整顺序写 snapshot test。

### 8.4 分阶段 Middleware

核心 Beta 必须实现：

1. Input sanitization
2. Tool output budget
3. Remote tool result sanitization
4. Thread data
5. Uploads
6. Sandbox lifecycle
7. Dangling tool-call repair
8. LLM error handling
9. Sandbox audit
10. Read-before-write
11. Tool error handling
12. Dynamic context
13. Durable context
14. Summarization
15. Todo/plan mode
16. Token usage
17. Title
18. System message coalescing
19. Subagent limit
20. Loop detection
21. Token budget
22. Terminal response recovery
23. Safety finish-reason repair
24. Clarification interrupt

后续补齐：

- Memory queue 和事实更新
- Skill activation 与 tool policy 的完整签名机制
- Deferred tool search 和 MCP routing auto-promotion
- 可插拔 authorization/guardrail provider
- 配置文件动态加载任意 middleware
- Vision image hidden-message 生命周期

Clarification middleware 必须保持在末尾，因为它会把 `ask_clarification` 转换为 interrupt。Safety 和 terminal recovery 必须在此之前完成。

## 9. Tool、MCP、Skills 和 Subagent

### 9.1 Tool Registry

统一工具描述：

```ts
interface DeerFlowTool<TInput = unknown, TOutput = unknown> {
  name: string;
  description: string;
  schema: z.ZodType<TInput>;
  source: "builtin" | "sandbox" | "mcp" | "community" | "subagent";
  risk: "read" | "write" | "execute" | "network";
  invoke(input: TInput, ctx: ToolContext): Promise<ToolResult<TOutput>>;
}
```

工具结果必须有统一 metadata：

- `status`
- `errorType`
- `recoverableByModel`
- `recommendedNextAction`
- `source`

模型可见文本和完整 artifact 应分离，避免将完整二进制、远端 HTML 或大量日志重新送回模型。

### 9.2 MCP

- 使用官方 `@modelcontextprotocol/sdk`。
- 支持 stdio、SSE/streamable HTTP 中当前项目实际需要的 transport。
- MCP connection 由进程级 registry 管理，不能每次 model call 新建。
- 工具 schema 统一转换为 Zod/JSON Schema。
- 设置 connect timeout、tool call timeout 和最大响应体。
- 配置更新后原子替换 registry；正在运行的 run 保留自己的工具快照。
- 首版不实现复杂 OAuth flow，可先支持 command/env、URL/header 和静态 token。

### 9.3 Skills

- 读取 `SKILL.md` YAML front matter 和正文。
- skill 路径必须 canonicalize，并限制在配置的 skill roots 内。
- 支持 `allowed-tools`、启停状态、slash activation 和 `describe_skill`。
- 使用 `contracts/slash_skill_contract.json` 验证解析器。
- skill 内容属于不可信数据，不能直接提升为系统权限。
- 首版只支持本地只读发现；在线安装、版本历史和 rollback 后置。

### 9.4 Subagent

Subagent 不应启动新的 Nest request。它由 Harness 内部的 `SubagentExecutor` 执行，并继承：

- `thread_id`
- root `run_id`
- `user_id`
- sandbox/thread workspace
- 授权后的工具子集
- token、turn 和 timeout budget
- tracing metadata

必须限制：

- 单次模型响应的并行 subagent 数量，建议默认 3、最大 4。
- 每个 root run 的总委派数，建议默认 6。
- 每个 subagent 的最大执行时间。
- subagent result 返回 lead agent 前的长度。

状态值直接使用 `contracts/subagent_status_contract.json`，不要从展示文本解析状态。

## 10. Sandbox

### 10.1 接口

```ts
interface Sandbox {
  id: string;
  exec(command: ExecRequest, signal?: AbortSignal): Promise<ExecResult>;
  readFile(path: string): Promise<Uint8Array>;
  writeFile(path: string, data: Uint8Array): Promise<void>;
  listDir(path: string): Promise<DirEntry[]>;
  stat(path: string): Promise<FileStat>;
}

interface SandboxProvider {
  acquire(ctx: SandboxAcquireContext): Promise<Sandbox>;
  get(id: string): Sandbox | undefined;
  release(id: string): Promise<void>;
  destroy(id: string): Promise<void>;
  shutdown(): Promise<void>;
}
```

### 10.2 实现顺序

1. `LocalSandboxProvider`：只用于可信开发环境，明确打印安全警告。
2. `DockerSandboxProvider`：生产基线，按 user/thread 隔离容器和 volume。
3. Remote/Provisioner adapter：后续项目，不进入首版。

安全要求：

- 禁止使用 Node.js `vm`、`eval` 或 worker thread 执行不可信代码。
- 宿主路径和虚拟路径必须分离。
- 所有文件路径使用 canonical path 做 root containment 检查。
- 容器默认无特权、非 root、只挂载 thread workspace 和只读 skills。
- 配置 CPU、内存、PID、磁盘、网络和执行时间限制。
- shell/tool 输出有字节上限。
- read-before-write 使用内容 hash，防止并发写覆盖模型未读的新内容。
- 文件工具和 shell 操作写入 audit event。

## 11. 配置系统

保持现有两个文件的概念，降低迁移成本：

- `config.yaml`：模型、数据库、Redis、sandbox、runtime、middleware 配置。
- `extensions_config.json`：MCP servers、skills 和 extension 状态。

使用 Zod 做启动时完整校验。以 `$ENV_NAME` 开头的值解析环境变量，但错误信息不能输出 secret 内容。

配置字段分为两类：

- 热加载：model 参数、prompt、tool 开关、skill 开关、summarization、token budget。
- 重启生效：database、Redis、checkpointer、stream bridge、sandbox provider、logging transport。

每次创建 run 时获取一个不可变 config snapshot。运行中的 run 不应因文件变化切换模型或工具。

首版不支持通过配置文件加载任意 npm module/class。该能力本质上是任意代码执行，只适合作为受信任 operator 扩展点，并应在后续以显式 plugin registry 方式实现。

## 12. 持久化设计

### 12.1 数据所有权

LangGraph 管理：

- checkpoint
- checkpoint writes
- graph store

DeerFlow TS 管理：

- `threads_meta`
- `runs`
- `run_events`
- `agents`
- `feedback`，如启用
- `users` 和 auth 表，如启用

不修改 LangGraph saver 自己的表。业务 migration 也不能尝试管理它们。

### 12.2 核心业务表

`runs` 至少包含：

- `run_id`
- `thread_id`
- `assistant_id`
- `user_id`
- `status`
- `model_name`
- `multitask_strategy`
- `metadata_json`
- `kwargs_json`
- `error`
- `stop_reason`
- token usage 聚合
- `owner_worker_id`
- `lease_expires_at`
- `created_at`、`updated_at`

`run_events` 至少包含：

- `thread_id`
- `run_id`
- `user_id`
- `event_type`
- `category`
- `content_json`
- `metadata_json`
- thread 内严格递增 `seq`
- `created_at`

`run_events` 的 seq 必须由数据库事务分配，不能使用进程内 counter。推荐对 thread counter row 使用 `SELECT ... FOR UPDATE`，或使用可证明无冲突的原子 SQL。

### 12.3 Python 数据兼容

不建议 TS 和 Python runtime 共用 checkpoint schema，原因包括：

- LangChain message 的跨语言序列化细节可能不同。
- 自定义 state reducer 和 channel version 表示可能不同。
- Python 自定义对象、artifact 和 metadata 不一定有 JS 等价类型。
- 两种 runtime 同时写同一 thread 会破坏 checkpoint lineage。

建议：

- 使用独立数据库或独立 PostgreSQL schema，例如 `deerflow_ts`。
- 只迁移业务级数据：用户、agent 配置、纯 JSON thread metadata 和 workspace 文件。
- 历史消息通过专门 importer 转换为规范 JSON，再在 TS 中建立新的初始 checkpoint。
- 切换期间以 thread 为单位单写，不做 Python/TS 双写。

## 13. 安全模型

核心 Beta 的最低安全要求：

- 所有 DTO `extra=forbid` 等价校验，拒绝未知危险字段。
- thread、run、upload、artifact 查询全部携带 `user_id` 过滤条件。
- artifact/upload 路径防 traversal 和 symlink escape。
- API key、MCP token、Git token 不写入 checkpoint、event 或日志。
- 远程网页、搜索和 MCP 返回值进入模型前做 tag neutralization。
- tool output 设置按字符、字节和 token 估算的上限。
- 客户端不能伪造 internal principal。
- Local sandbox 在生产配置中默认拒绝启动，除非显式 opt-in。
- 所有 execute/write/network 工具经过审计。
- 文件上传先写临时文件，校验大小后原子 rename。
- shutdown 时有界等待 run、memory queue、MCP client 和 sandbox 清理。

完整 RBAC 可以后置，但 Principal 接口应在首版存在：

```ts
interface Principal {
  userId: string;
  role: string;
  isInternal: boolean;
  attributes: Readonly<Record<string, unknown>>;
}
```

这样后续加入 authorization provider 时不需要改写所有 ToolContext 和 repository 接口。

## 14. 测试策略

### 14.1 测试层级

| 层级 | 内容 |
| --- | --- |
| Unit | reducers、middleware、config、path、tool result normalization |
| Contract | 现有 JSON contracts、DTO snapshot、SSE frame、event category |
| Integration | PostgreSQL saver、repository、Redis Streams、MCP transport、Docker sandbox |
| E2E | Nest Gateway + fake model + real graph + PostgreSQL/Redis |
| Live smoke | 真实模型的文本、tool calling、interrupt、subagent |

### 14.2 测试基础设施

- 使用 deterministic fake chat model，不依赖真实 API 做 CI 主路径。
- Testcontainers 启动 PostgreSQL、Redis 和 sandbox 测试容器。
- 用慢消费者测试 SSE backpressure。
- 用断连、重连、取消竞争测试 RunManager。
- 用两个 Gateway process 测试 owner lease、cross-process join 和 cancel。
- 所有 middleware 都有顺序 snapshot 和关键相邻约束测试。
- 为 path traversal、secret context 注入和 symlink escape 建立负向测试。

### 14.3 核心验收场景

1. 创建 thread，发送消息，收到 token delta、最终 `values` 和 `end`。
2. 同一 thread 第二轮能读取上一轮 checkpoint。
3. 模型调用 sandbox tool，tool call、tool result 和最终回答顺序正确。
4. SSE 断开且 `on_disconnect=continue` 时 run 继续，稍后可 join。
5. SSE 断开且 `on_disconnect=cancel` 时 run 进入 interrupted。
6. `reject` 对同 thread 并发返回 409。
7. `interrupt` 终止旧 run 并启动新 run。
8. `rollback` 恢复到旧 run 前 checkpoint。
9. `ask_clarification` 产生 interrupt，提交回答后可恢复。
10. MCP tool、skill policy 和 subagent 都不能绕过 tool allowlist。
11. Gateway 重启后 thread state、run history 和 events 可读取。
12. 多实例下，非 owner 实例可以订阅 Redis stream，并正确处理取消。

## 15. 性能和可靠性目标

核心 Beta 建议采用以下可测目标：

- 除模型首 token 延迟外，Gateway 引入的 P95 首帧开销小于 100 ms。
- model chunk 到 SSE publish 的 P95 额外延迟小于 50 ms。
- 单个 run 的内存事件缓冲有硬上限，慢客户端不能无限占用内存。
- run terminal 状态、最后 event 和 stream END 的顺序可重复验证。
- PostgreSQL 模式下 thread 内 event seq 无重复且严格递增。
- 进程退出不接受新 run，并在配置超时内完成或中断现有 run。
- 生产环境不因单个 MCP server 或 tool 超时阻塞整个事件循环。

性能测试不要以模型吞吐作为 Gateway 指标；模型延迟和后端额外延迟应分开记录。

## 16. 实施阶段

### 阶段 0：技术验证，1 至 2 周

交付物：

- NestJS `/health` 和一个 SSE endpoint
- LangGraph.js model-tool loop
- PostgreSQL checkpoint 的两轮对话
- tool-call argument delta streaming
- interrupt/resume
- `AbortController` cancel
- Redis Streams publish/join
- 一页验证报告和 go/no-go 结论

Go 条件：

- 六项核心行为都有自动化测试。
- 不需要 patch `node_modules`。
- checkpoint 和 stream 不依赖私有、明显不稳定的 LangGraph API。
- middleware 缺口可由局部 StateGraph adapter 补齐。

No-go 条件：

- 无法稳定获得 tool-call delta 或 subgraph namespace。
- interrupt/resume 无法在 PostgreSQL saver 上复现。
- cancel 无法贯穿模型与工具调用，且没有可接受的隔离替代方案。

No-go 不代表放弃 TypeScript；它意味着应自建显式 StateGraph runner，而不是依赖高层 `createAgent`。

### 阶段 1：骨架与契约，2 周

- pnpm monorepo、lint、test、build、Dockerfile
- contracts 和 Zod DTO
- ConfigModule
- Drizzle schema 和 migration
- threads、runs、health 基础 API
- fake model E2E

### 阶段 2：Runtime，3 至 4 周

- RunManager 和状态机
- Checkpointer
- Memory/Redis StreamBridge
- SSE、wait、join、cancel
- event journal
- thread 并发策略
- shutdown 和故障恢复

### 阶段 3：Harness，4 至 5 周

- Lead Agent 和 state reducers
- 模型工厂
- P0 middleware
- prompt、title、summary、todo、usage
- clarification interrupt
- contract tests

### 阶段 4：工具生态，3 至 4 周

- Local/Docker sandbox
- 文件和 shell 工具
- MCP registry
- Skills
- Subagent
- uploads 和 artifacts

### 阶段 5：生产加固，2 至 3 周

- Redis 多实例测试
- owner lease 和 orphan recovery
- security review
- load/failure tests
- OpenTelemetry
- deployment 文档和升级策略

阶段存在重叠，2 名工程师可以并行 Runtime 与 Harness，但 contracts 和 spike 必须先完成。

## 17. 人力估算

| 目标 | 2 名资深工程师 | 单人 |
| --- | --- | --- |
| PoC | 1-2 周 | 2-3 周 |
| 可演示 MVP | 6-8 周 | 3-4 个月 |
| 可部署核心 Beta | 12-16 周 | 5-7 个月 |
| 接近当前后端核心能力 | 5-8 个月 | 9-15 个月 |

估算假设：

- 工程师熟悉 TypeScript、NestJS、流式系统和 PostgreSQL。
- 至少一人理解 LangGraph checkpoint 和 tool calling。
- 不同时开发 Frontend、Channel、Scheduler、RAG 和 Provisioner。
- 使用现有 DeerFlow prompt、contract 和行为测试作为参考。

最大的估算误差来自 middleware 细节、多实例 run 恢复和 sandbox provider，而不是 NestJS Controller。

## 18. 主要风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| JS middleware 与 Python 不等价 | 行为无法逐项移植 | 第 1 周 spike；DeerFlow 自有 adapter；必要时显式 StateGraph |
| Checkpoint 跨语言不兼容 | 不能原库切换 | 独立 schema；JSON importer；thread 单写切换 |
| SSE 慢消费者 | 内存增长、run 阻塞 | 有界 buffer、Redis Streams、写超时、断开策略 |
| Cancel 只停 HTTP 不停工具 | 后台泄漏进程 | AbortSignal 全链路；sandbox 进程组终止；取消 E2E |
| 同 thread 并发写 checkpoint | 历史损坏 | DB partial unique index、thread lock、条件状态更新 |
| Local sandbox 被误用 | 宿主机命令执行 | 生产默认禁用；容器 provider；启动警告和配置 gate |
| 动态 MCP/skill 配置漂移 | run 中途工具变化 | 每个 run 使用不可变 registry/config snapshot |
| 模型 provider 差异 | 空消息、tool-call 格式错误 | provider adapter、terminal/safety middleware、fixture tests |
| 多实例 owner 失联 | run 悬挂 | worker lease、orphan reconciliation、Redis bridge |
| 全量对齐范围持续膨胀 | 无法按期交付 | 以 P0/P1/P2 contract 管理范围，新增能力单独 RFC |

## 19. 迁移和发布策略

推荐采用旁路替换：

1. TS Gateway 使用独立端口、数据库 schema 和 Redis key prefix。
2. 先跑 contract tests 和录制流量回放，不接生产写流量。
3. 选择测试用户或新 thread 进入 TS runtime。
4. 已进入 TS 的 thread 保持单写，不在 Python/TS 间往返。
5. 比较 run event、最终消息、tool calls、token usage 和错误率。
6. 按用户或新 thread 百分比逐步放量。
7. 保留 Python Gateway 的流量级回滚，但不要回滚已经由 TS 写过的 thread 到 Python checkpoint。

如果没有迁移现有数据的要求，最简单可靠的方案是让 TS 版本作为独立产品启动，只复用公开 contract 和 skills 目录格式。

## 20. 首批 ADR 建议

项目开始时应落地以下 Architecture Decision Records：

1. NestJS + Fastify，而非 Express。
2. PostgreSQL-first，暂不支持 SQLite。
3. Drizzle + 显式 SQL migration。
4. Harness 禁止依赖 NestJS/Gateway。
5. 独立 TS checkpoint schema，不与 Python 双写。
6. Memory bridge 用于开发，Redis Streams 用于生产。
7. `createAgent` 优先、显式 StateGraph 作为内部 fallback。
8. 容器是生产 sandbox 的最小安全边界。
9. Wire contract 优先于内部实现兼容。
10. Middleware 顺序属于受测试的公开行为。

## 21. 最终建议

建议立项，但不要直接开始“完整重写”。正确的第一步是完成阶段 0，并把以下四项作为硬门槛：

- PostgreSQL checkpoint 两轮对话
- tool-call delta 的 SSE 兼容输出
- interrupt/resume/cancel
- middleware 动态过滤工具和包装 tool call

如果这四项成立，NestJS Gateway、MCP、Skills、Sandbox 和 Subagent 都属于可控的常规工程工作。若其中任何一项依赖不稳定私有 API，应立即切换到 DeerFlow 自有显式 StateGraph runner，避免在项目后期重写 Runtime。

对该项目最重要的边界不是 NestJS 与 LangGraph，而是：Gateway 负责信任和协议，Runtime 负责运行生命周期，Harness 负责 Agent 行为。只要这三个层次从第一天保持独立，TypeScript 版本具备长期维护和扩展的可行性。
