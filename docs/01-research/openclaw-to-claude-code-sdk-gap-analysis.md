# OpenClaw 切换 Claude Code SDK 能力差距分析

- 状态：草案，待产品与技术确认
- 日期：2026-09-11
- 目标：识别当前 OpenClaw 运行路径的真实能力、Claude Code SDK 可替换范围、不可直接等价的能力及迁移风险
- 约束：本文只做分析，不授权修改运行代码或移除 OpenClaw

## 1. 结论摘要

当前仓库并不是只把 OpenClaw 当作一次模型调用，而是同时依赖它承担 Agent 工作区、身份与 Memory 文件、Skills、会话隔离、工具执行、公开动作流和工程文件采集。切换 Claude Code SDK 可以覆盖核心 Agent 执行循环，但不能把“换一个 SDK 包”视为完整迁移。

Claude Code SDK 可原生或通过薄适配层覆盖：模型回合、文件读写、Shell、代码修改、工具事件、会话恢复、Skills、MCP 和受限子 Agent。以下能力没有直接一对一替代，必须由江湖 Online 或独立服务承接：Matrix/多渠道 Gateway、长期调度、平台审批、跨 Agent 公共消息、正式 Artifact、版本化返工、持久化恢复和历史审计。

迁移前必须先运行并冻结真实 OpenClaw 能力基线。仅依赖 Mock 单测不能证明实际能力没有回退。

## 2. 当前实现证据

| 当前职责 | 代码或配置证据 | 当前所有者 |
| --- | --- | --- |
| Run 级运行时隔离 | `server/app/openclaw_runtime.py` 的 `for_run` | OpenClaw Adapter |
| Agent 级 Workspace | `workspace_path`、`delivery` 目录 | OpenClaw Adapter + 平台 |
| 身份、Persona、规范和 Memory | `IDENTITY.md`、`SOUL.md`、`AGENTS.md`、`MEMORY.md` | 平台生成，OpenClaw 装载 |
| Skills | Agent Skills 写入独立目录并登记到 OpenClaw 配置 | 平台生成，OpenClaw 装载 |
| 模型配置与逐节点模型覆盖 | `sync` 和 `message` 的模型配置 | 平台 + OpenClaw |
| 文件、命令和测试工具 | coding tool profile | OpenClaw |
| 实时公开动作 | Session JSONL 解析，映射 progress/tool_call/tool_result | OpenClaw Adapter |
| 隐藏思维保护 | Session 解析时忽略 thinking 并脱敏 Token | OpenClaw Adapter |
| 文件变更采集 | Workspace 前后快照 | 平台 Adapter |
| 多人工程提交 | `publish_workspace_submission` | 平台 Adapter |
| 正式工程树晋升 | `promote_workspace_tree` | 平台 Adapter |
| 多 Agent 并行、合议、Judge、返工 | `platform_executor.py` | 江湖 Online |
| 暂停、恢复、取消、预算 | `platform_executor.py`、`platform_store.py` | 江湖 Online |
| Matrix/Synapse | `compose.yaml`、`docker/synapse/` | 正在建设的平台通信平面 |
| 镜像内运行时 | `Dockerfile` 固定安装 OpenClaw | Docker 构建 |
| 真实验收 | `scripts/verify-real-openclaw-e2e.py` | OpenClaw 专用脚本 |

## 3. Claude Code SDK 核验事实

截至 2026-09-11，通过 npm 包元数据核验：

- 现行包名为 `@anthropic-ai/claude-agent-sdk`，README 明确说明 Claude Code SDK 已更名为 Claude Agent SDK。
- 核验版本为 `0.3.268`，内含 Claude Code `2.1.268`。
- Node.js 要求为 18 或更高版本；当前项目 Node.js 24 满足要求。
- SDK 提供 `query`、`sessionId`、`resume`、Claude Code 内置工具、Skills、MCP、子 Agent、Hooks、工具事件、用量和文件 checkpoint 等能力。
- SDK 使用条款和 README 包含数据收集说明，生产部署前必须确认隐私、遥测和商业条款。
- Claude Code SDK 的模型协议不是 OpenAI Responses 的通用兼容层，现有 `openai-responses` 配置不能假设可直接复用。

## 4. 能力映射

| OpenClaw 当前能力 | Claude Code SDK 方案 | 判断 |
| --- | --- | --- |
| Agent 独立身份 | 每个 Agent 独立 Workspace、`CLAUDE.md` 和身份文件 | 可替换 |
| 长期 Memory | 平台数据库仍是真相源，每轮投影到 Agent 私有 Memory 文件 | 可替换 |
| Skills | `.claude/skills` 或 SDK Skill 配置 | 可替换，但需验证发现规则 |
| 独立 Session | `sessionId`、`resume` 与平台 Session 映射表 | 可替换 |
| 文件读写与编辑 | Read/Write/Edit 等 Claude Code 工具 | 可替换 |
| Shell、构建与测试 | Bash 工具或受控 MCP Tool Gateway | 可替换，但权限语义不同 |
| 工具动作流 | SDK assistant/user/result/tool 消息归一化 | 可替换 |
| 子 Agent | SDK Agent/Task | 可替换，但必须限制深度、工具和预算 |
| 多 Agent 并行 | 继续由 `platform_executor.py` 并行调用独立 SDK Session | 平台保留 |
| 公共消息与合议 | 继续由平台生成公开 dossier/message，不共享私有 Session | 平台保留 |
| 文件变更、提交、晋升 | 沿用现有快照和 promotion 逻辑 | 平台保留 |
| Judge、返工、Gate | 继续由平台控制 | 平台保留 |
| 沙箱 | Docker/独立 Workspace + SDK 权限和可选 Sandbox | 组合替换，必须实测 |
| MCP 工具 | SDK 原生 MCP 配置 | 可替换 |
| Matrix/多渠道 Gateway | 独立 Matrix Bridge 或平台通信服务 | SDK 无直接等价能力 |
| 定时任务 | 平台 Scheduler/Worker | SDK 无持久调度等价能力 |
| 后台长期任务 | 平台 Worker + 持久状态；SDK background task 只作为进程内能力 | 不能直接等价 |
| OpenAI Responses 模型 | 保留独立 Native Adapter，或明确停止支持 | Claude SDK 不直接覆盖 |

## 5. 相比初步计划发现的遗漏

### 5.1 模型与认证

1. 当前平台同时支持 `anthropic-compatible` 和 `openai-responses`；Claude Code SDK 不能自动保持后者。
2. 自定义 Anthropic Gateway 需要验证 `ANTHROPIC_BASE_URL`、API Key/Bearer Token 和自定义 Header 的真实行为。
3. SDK 模型别名和平台保存的完整模型 ID 可能不一致，需定义映射和不可用错误。
4. 主 Agent 与 SDK 子 Agent 的 Token、成本统计口径不同，必须以 `modelUsage` 等完整字段核对。

### 5.2 权限与安全

1. 不能默认使用 `bypassPermissions`；必须明确采用工具白名单、`canUseTool`、MCP Tool Gateway 或容器沙箱中的哪一种组合。
2. Bash 的命令级权限与 OpenClaw `exec/process` 不同，不能仅按工具名放行。
3. WebFetch/WebSearch、网络出口、Git、包管理器和外部写操作需要独立策略。
4. Agent 必须只能读写自己的 Workspace 和获准目录，需覆盖路径穿越、符号链接和硬链接。
5. SDK thinking、tool input、stderr、hook 和子 Agent 消息都需要统一脱敏，不能只过滤 assistant thinking block。
6. SDK README 中的数据收集和隐私条款需要形成正式部署决定。

### 5.3 会话、进程与恢复

1. 需要决定每个回合启动一个 SDK Query 进程，还是维护长连接 Query；两者影响取消、并发和恢复。
2. `sessionId/resume` 与平台 run/task/attempt 的映射必须持久化，且不能用模型 Session 作为正式状态。
3. API 进程重启时需要识别孤儿 Claude 进程、未知状态和迟到结果。
4. 暂停不能只停止平台调度，还要定义正在执行的 SDK 工具是否允许完成。
5. 取消必须级联终止主进程和 SDK 子 Agent，并隔离迟到输出。

### 5.4 多 Agent 与外部通信

1. SDK 子 Agent 不能绕过平台自行形成正式团队或发布正式产物。
2. 平台并行 Agent 与 SDK 内部子 Agent 是两套层级，必须分别计数、限额和审计。
3. 当前正在建设的 Matrix/Synapse 不能再假设由 OpenClaw Matrix Channel 提供，需要独立 Bridge 方案。
4. 多渠道身份、账号绑定、消息线程和 @提及不属于 Claude Code SDK 核心能力。

### 5.5 数据、API 与兼容迁移

1. 数据库中 `runtime` 默认值和现有记录为 `openclaw`，需要版本化迁移。
2. 历史 Run 事件中的 `openclaw.*` 必须保留，不应重写历史审计。
3. `/api/platform/openclaw/status`、前端文案、脚本和监控需明确兼容期及移除时间。
4. 真实验收脚本和测试名称不能直接重命名后继续沿用，必须验证断言仍然有意义。
5. Docker 镜像需验证 SDK 原生二进制、Node optional dependency、Linux 架构和离线安装。

### 5.6 测试与发布

1. 必须在卸载 OpenClaw 前完成真实运行基线，否则以后无法证明能力等价。
2. Mock 合同测试、真实 E2E、故障注入和安全测试需要分层，不能用单一通过率替代。
3. 模型输出文本不适合逐字比较，应比较事件、工具、文件、产物、验收和安全属性。
4. 需要设定真实测试的 Token/费用上限和可重复次数。
5. 需要临时的非生产双 Adapter 对照工具，但生产路径最终只能有一个默认 Runtime。

## 6. 风险分级

| 风险 | 等级 | 处理门禁 |
| --- | --- | --- |
| OpenAI Responses 配置失效 | 高 | D-001 决策后才能设计 Adapter |
| 工具权限扩大或外部写操作失控 | 高 | 权限模型和安全用例全部通过 |
| Matrix/渠道能力被静默删除 | 高 | 独立通信架构决策 |
| 暂停、取消、恢复产生孤儿进程或重复产物 | 高 | 故障注入和幂等测试通过 |
| 子 Agent 绕过平台预算与审计 | 高 | 默认禁用或受限启用并形成事件 |
| SDK 数据收集不符合部署要求 | 高 | 法务/产品部署决定 |
| Skills、Memory 装载效果变化 | 中 | 真实同题能力基线对照 |
| Docker 多架构或离线构建失败 | 中 | 镜像构建和冷启动测试 |
| 成本和 Token 统计口径变化 | 中 | 统一用量 Schema 和对账测试 |

## 7. 推荐结论

推荐迁移目标不是“所有能力都交给 Claude Code SDK”，而是：

```text
江湖 Online 领域运行时
  + Claude Code SDK Agent Execution Adapter
  + 平台 Tool/Approval Gateway
  + 平台 Workspace/Artifact/Memory
  + 独立 Matrix Bridge
  + 独立 Scheduler/Worker
```

只有在真实 OpenClaw 基线冻结、关键决策完成、同一测试集通过后，才允许移除 OpenClaw 生产依赖。
