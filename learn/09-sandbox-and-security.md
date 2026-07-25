# 09 Sandbox 与 Agent 安全

## 1. 安全原则

Agent 安全不能依赖“模型会听话”。DeerFlow 使用纵深防御：

```text
能力裁剪
→ Prompt 权限分层
→ Guardrail 授权
→ 命令审计与读写门禁
→ Sandbox 隔离
→ Secret 管理
→ 输出预算与脱敏
→ Journal 与追踪
```

任何单层都不是完整安全边界。

## 2. 威胁模型

需要保护：

- Gateway 宿主机；
- 用户/线程文件；
- 平台 API key 和数据库连接；
- 外部 SaaS/GitHub；
- Checkpoint/Run record；
- token 成本和系统可用性；
- Agent 配置和 Skill 供应链。

威胁来源：

- 恶意用户；
- 网页/MCP/Tool output prompt injection；
- 恶意 Skill；
- 失陷 MCP Server；
- 模型错误参数；
- 错误配置；
- 跨用户/跨线程访问；
- 无限命令、循环工具和大输出。

## 3. Sandbox 抽象

`Sandbox` 提供：

- execute command；
- read/write/update/download；
- list/glob/grep；
- env 与 timeout。

`SandboxProvider` 管理：

- acquire；
- get；
- release；
- reset；
- shutdown。

Sandbox ID 应与 user/thread 绑定，避免同 thread ID 跨租户复用。

## 4. Local Sandbox

Local 模式最终使用 Gateway 宿主 subprocess 和文件系统，因此：

> LocalSandbox 是开发便利层，不是 OS 安全隔离边界。

防护包括：

- host bash 默认禁用；
- per-user/per-thread path mappings；
- `/mnt/...` 虚拟路径；
- read-only mounts；
- process group timeout；
- stdin `/dev/null`；
- bounded stdout/stderr；
- secret-looking inherited env scrub；
- 宿主路径反向隐藏。

但自定义 Python Tool 若直接使用 `Path` 或 `subprocess`，可绕过这些保护。

## 5. AIO Sandbox

AIO 使用容器或远端 provisioner：

- user/thread 确定性 sandbox；
- 进程内锁与跨进程 file lock；
- discover/reuse；
- readiness polling；
- warm pool；
- idle cleanup。

普通命令复用持久 shell session；带 request secret 的命令使用结构化 `bash.exec(env=...)` 和新 session，避免 secret 残留。

若旧镜像不支持安全 env API，系统 fail-fast，而不是把 secret 拼入 command。

## 6. BoxLite

BoxLite 使用 micro-VM，Provider 维护专用 asyncio loop/thread，所有 loop-affine SDK 调用通过 `run_coroutine_threadsafe()` 执行。

特点：

- VM 级隔离更强；
- user/thread 确定性名称；
- warm pool；
- command env 结构化注入；
- 文件分块写入；
- download 大小上限。

VM 隔离不等于应用最小权限；Tool 层仍应限制虚拟路径和可访问文件。

## 7. 虚拟路径

Agent 看到：

- `/mnt/user-data/workspace`；
- `/mnt/user-data/uploads`；
- `/mnt/user-data/outputs`；
- `/mnt/skills`；
- `/mnt/acp-workspace`。

Local 模式映射宿主路径，AIO 通过 volume，BoxLite 在 VM 中创建。

安全实现要：

- 拒绝 `..`；
- canonical resolve 后验证仍在 root；
- 使用 segment boundary，不用裸 `startswith`；
- 校验 symlink；
- 区分 read-only mount；
- 输出中隐藏宿主绝对路径。

## 8. Guardrail

Guardrail 在工具执行前获得：

- tool name/input；
- user/role；
- agent/thread/run/tool call；
- OAuth identity；
- subagent 标记。

可实现 RBAC/ABAC/参数策略。Provider 异常可配置 fail-open/fail-closed，高风险工具应默认 fail-closed。

Guardrail 决策是确定性授权，不应由 LLM 自由文本决定。

## 9. Sandbox Audit

Audit 主要扫描 Bash command：

- destructive commands；
- pipe-to-shell；
- reverse shell；
- cloud metadata；
- `/proc/*/environ`；
- `LD_PRELOAD`；
- fork bomb；
- 系统文件写入。

它是启发式检测，只覆盖名为 `bash` 的工具，不能替代容器/VM，也不能覆盖自定义 Tool/MCP 内部副作用。

## 10. Read-before-write

流程：

1. `read_file` 成功后在 ToolMessage 写 path + content hash；
2. 写现有文件前重新读取并算 hash；
3. 找最近 read mark；
4. hash 一致才允许写；
5. 写后文件变化，旧 mark 自动失效。

按 `(scope, path)` 加锁，防同轮并行写复用一个旧 mark。Mark 随消息被 summarization 删除时自动失效。

边界：

- 只覆盖标准 write/replace Tool；
- Bash/MCP/自定义 Tool 可绕过；
- 不可检查时会 fail-open；
- 它是 correctness guard，不是文件授权系统。

## 11. Secret 安全

### 不应出现的位置

- Prompt；
- Tool args；
- command string；
- Checkpoint；
- Run record；
- trace metadata；
- audit value；
- stdout。

### 安全路径

```text
request context
→ live Skill registry 授权
→ runtime active secret bindings
→ Sandbox structured env
→ output redaction
```

宿主环境先 scrub，再覆盖 request-provided secret，避免平台 key 自动泄漏到技能进程。

### 剩余风险

- 很短的 secret 可能不适合按值替换；
- Skill 可主动外传环境变量；
- 网络 egress 仍需限制；
- static sandbox/MCP env 是长期凭据，不具备 request scope。

## 12. SSRF

Community fetch 工具会阻止：

- 非 HTTP(S)；
- localhost；
- private/loopback/link-local/reserved/multicast；
- metadata host。

剩余风险：

- DNS rebinding；
- 重定向目标未重新校验；
- 远端抓取服务可访问内网；
- 运维开启 allow-private 降级。

更强方案包括 DNS pinning、每跳重定向校验、sandbox egress allowlist 和网络策略。

## 13. Prompt Injection

来源可能是：

- 网页；
- MCP 返回；
- Skill 文档；
- Tool output；
- Memory；
- Summary；
- Subagent result。

应对：

- 明确不可信数据角色；
- 固定 authority contract；
- Side-effect Tool 由 Guardrail 授权；
- Tool schema 暴露不等于执行授权；
- 高风险动作要求用户批准；
- 读取 Agent 与执行 Agent 分权；
- 不依赖简单关键词过滤。

## 14. 资源与成本安全

- recursion limit：图步骤；
- TokenBudget：本 Run token；
- ToolProgress：无新信息工具；
- LoopDetection：重复调用模式；
- ToolOutputBudget：结果大小；
- command timeout：墙钟时间；
- Subagent timeout/max turns/concurrency；
- upload/download 大小；
- warm pool capacity；
- provider rate limit retry。

安全既包括机密性，也包括成本和可用性。

## 15. 多租户检查清单

- user ID 是否来自认证上下文，而非 client args？
- thread owner 是否验证？
- sandbox ID 是否含 user + thread？
- MCP session 是否含 user + thread？
- 文件路径是否进入正确 owner bucket？
- Memory 是否按 user/agent？
- Repository 查询是否 owner-filtered？
- background thread 是否显式携带 user？
- custom mount 是否跨租户共享可写目录？
- external service token 是否用户级还是部署共享？

## 16. 面试题

### 1. LocalSandbox 为什么不安全？

它仍在 Gateway 宿主执行，工具层路径约束不能替代 kernel/container/VM 隔离。

### 2. Guardrail 与 Sandbox 的区别？

Guardrail 决定“允许做什么”，Sandbox 限制“即使执行也能影响到哪里”。

### 3. Read-before-write 为什么不是完整访问控制？

覆盖能力有限且存在 fail-open，不能约束 Bash/MCP/自定义写入。

### 4. 为什么 secret env 需要新 shell session？

防止秘密残留在持久会话，被后续请求读取。

### 5. 如何防 Tool output prompt injection？

降权为不可信数据，对副作用工具进行确定性授权，关键动作加入审批，不依赖内容关键词清洗。
