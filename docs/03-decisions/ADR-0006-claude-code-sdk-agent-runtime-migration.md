# ADR-0006：Agent 运行底座迁移到 Claude Code SDK

- 状态：已接受并进入 G6-G7 实施验收；代码切换已完成，真实 UI E2E 第 7 版仍在整改，尚未达到最终 `gate.passed + run.completed`
- 日期：2026-09-11
- 决策范围：江湖 Online 默认 Agent Execution Adapter
- 上游依据：ADR-0005、当前 OpenClaw 实现、能力差距分析
- 说明：用户已确认完整替换范围并授权代码修改与真实端到端验收；当前生产 Registry 固定为 Claude Code SDK，最终完成结论仍受真实 UI E2E、全量回归和残留扫描约束

## 1. 背景

平台原先默认通过 OpenClaw 执行真实 Agent 回合。当前代码已经以 Claude Code SDK 承接实际 Agent 模型与工具循环，并继续保持平台的多 Agent 协作、对抗、文件交付、审计和恢复能力；是否完整通过仍由真实第 7 版 UI Run 裁决。

ADR-0005 规定平台领域状态与 Agent Adapter 解耦，因此本次迁移不得把 Claude Code Session、Task 或工具记录升级为正式 Workflow、Artifact 或 Decision 真相源。

## 2. 提议决策

在能力基线和关键决策通过后：

1. 默认 Agent Execution Adapter 从 OpenClaw 切换为 Claude Code SDK。
2. 江湖 Online 继续拥有 Workflow、Run、Task、Agent、Memory、知识、权限、预算、Artifact、Evidence、Gate、Judge、返工和审计。
3. Claude Code SDK 只拥有单个受控 Agent 回合内的模型与工具循环。
4. Matrix、渠道、调度和持久后台任务由平台或独立服务实现，不声明为 Claude Code SDK 原生能力。
5. 历史 OpenClaw 事件和数据保持原样可读；新 Run 使用新的 runtime 标识和事件类型。
6. 生产环境最终不保留静默 OpenClaw fallback。迁移验证期可在非生产工具中并行运行两种 Adapter。
7. 在真实 OpenClaw 能力基线冻结前，不允许卸载 OpenClaw 或改写默认生产路径。
8. 本次只替换 OpenClaw 承担的运行能力；其他产品功能、系统边界、Matrix/Synapse、Workflow、API 行为、数据语义和用户体验保持不变。
9. Claude Code SDK 没有原生等价能力时，由 Claude Adapter、平台服务或 MCP 补齐，不能以迁移为由删除或降级原有能力。

## 3. 关键决策清单

### D-001：现有 OpenAI Responses 模型怎么办

- 状态：已确认（2026-09-11）
- 事实：平台模型配置支持 `anthropic-compatible` 与 `openai-responses`；Claude Code SDK 不是 OpenAI Responses 通用执行器。
- 决策：保留独立 Native/OpenAI Agent Adapter，Claude Code SDK 成为 Anthropic 类模型的默认 Adapter。产品层称为“默认底座切换”，不删除多模型能力。
- 备选：停止 Agent Runtime 对 OpenAI Responses 的支持，仅保留其用于非 Agent 的普通 LLM 生成。
- 不推荐：将 OpenAI Responses 网关伪装成 Anthropic 接口且不做正式兼容测试。
- 影响：决定 Runtime 路由、模型设置 UI、测试矩阵和数据迁移。

G3 核验补充：用户当前保存的 `openai-responses / gpt-5.6-sol` Endpoint 实际同时支持 Anthropic Messages，并已通过 Claude Agent SDK 真实 Query。因此“当前这项配置”可由 Claude Adapter 使用；保留 Native/OpenAI Adapter 的决定仍用于其他只支持 OpenAI Responses 的配置，不能泛化为所有 OpenAI Endpoint 都可直接进入 Claude SDK。

### D-002：Matrix 与渠道能力归谁

- 状态：已确认（2026-09-11）
- 决策：Matrix/Synapse 及其他非 OpenClaw 产品能力保持不变。OpenClaw 原先承担的渠道连接或消息投影能力由 Claude Adapter、平台独立 Bridge 或 MCP 补齐；Claude SDK 只接收平台筛选后的消息和介入。
- 原因：迁移只替换底座，不改变产品功能；同时避免外部消息绕过平台权限和审计边界直接进入私有 Session。

### D-003：工程工具如何授权

- 状态：已按“其他保持不变”原则收敛（2026-09-11）
- 决策：保持当前权限效果。工程 Agent 获得受控的文件、编辑、命令和进程能力；非工程 Agent 保持最小工具集。默认不使用全局 `bypassPermissions`，通过 Workspace 边界、工具白名单、SDK `canUseTool` 或 MCP Tool Gateway 实现等效权限。
- 原因：迁移不能扩大或缩小现有 Agent 权限，仅按 Bash 工具名全局放行无法满足当前隔离效果。

### D-004：是否允许 Claude SDK 自行派生子 Agent

- 状态：已按能力等效原则收敛（2026-09-11）
- 决策：保留 OpenClaw 原有的受控子 Agent 能力。只有平台节点政策明确允许时才开放 Claude SDK 子 Agent，并限制深度、并发、工具、模型和预算；默认节点不得自行扩张团队。
- 原因：既不能删除 OpenClaw 能力，也不能让 SDK 子 Agent 绕过平台编排、费用和审计。

### D-005：SDK 进程和 Session 生命周期

- 状态：已按当前运行行为收敛（2026-09-11）
- 决策：每个受控回合使用一个可取消 Query 进程，Session ID 持久映射；完成后结束进程，后续回合通过 `resume` 恢复。
- 原因：这与当前每次 message 启动独立 OpenClaw 子进程、Session 状态独立保存的效果最接近，也便于隔离 Run、回收资源和处理 API 重启。

### D-006：SDK 遥测和数据收集

- 状态：已按不扩大数据暴露原则收敛（2026-09-11）
- 决策：关闭可关闭的非必要遥测和网络流量；正式核验 Anthropic 商业条款、数据使用政策，并把最终配置写入部署文档。除完成模型请求所必需的数据外，不新增对外数据发送。
- 原因：迁移后的数据暴露范围不得超过当前系统行为。

### D-007：切换与回滚方式

- 状态：已按当前显式失败原则收敛（2026-09-11）
- 决策：测试环境按同一测试集双跑；生产切换按版本发布，保留上一镜像作为人工回滚手段，新版本内部不静默回退 OpenClaw。
- 原因：当前 OpenClaw 不可用时会明确失败而不是伪造降级结果；迁移后保持相同语义，镜像级回滚也更容易审计。

## 4. 必须保持的架构边界

- Claude Code 的完成不等于平台 Task 完成。
- SDK tool result 只能形成 Action/Evidence/CandidateArtifact。
- SDK Session 不能代替平台 Run、Attempt 或 Checkpoint。
- 子 Agent 不能自行发布正式 Artifact。
- Agent 不能读取其他 Agent 的私有 Session、Memory 或未授权知识。
- 历史 `openclaw.*` 事件不得批量改写成 `claude_code.*`。
- 取消或超时后到达的迟到结果不得晋升为正式产物。

## 5. 接受门禁

本 ADR 只有同时满足以下条件才可改为“接受”：

1. D-001 至 D-007 已按用户确认或“能力等效、其他不变”的保守规则收敛。
2. OpenClaw 真实能力基线已冻结并可重复执行。
3. Claude Code SDK Adapter 通过相同合同和 E2E 测试。
4. 安全、隐私、许可证和部署方式完成核验。
5. Matrix、调度和外部写操作不存在未声明的能力丢失。
6. 用户审阅能力对照报告并批准生产切换。

## 6. 当前决策状态

当前关键决策已收敛并被用户接受。G1 能力基线、G2 Runtime Port、G3 技术探针、G4 Claude Adapter、G5 同题对照和 G6 代码切换均已执行；生产 Registry 只允许 `claude_code`，镜像不安装 OpenClaw，历史 API/事件保持只读兼容。真实第 7 版 UI Run 已完成独立审计和两次真实 Judge 退回，sequence 1879/1880 证明预期退回后继续下游，sequence 1881 已启动整改。最终状态仍是“验收中”，只有本 Run 出现 `gate.passed` 与 `run.completed` 才可把 ADR 状态改为最终完成。
