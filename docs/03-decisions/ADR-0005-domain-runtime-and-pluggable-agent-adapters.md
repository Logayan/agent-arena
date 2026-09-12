# ADR-0005：领域运行时与可插拔 Agent 执行适配层

- 状态：接受
- 日期：2026-07-27
- 决策范围：江湖 Online MVP 系统架构与多 Agent 框架选型
- 上游依据：`jianghu-online-prd-v1.0.md`、`user-requirements-v2.md`
- 研究依据：OpenClaw、Microsoft Agent Framework、LangGraph、AgentScope、CrewAI、ChatDev、MetaGPT、CAMEL、EvoAgentX、GEAR、GAIA Blackboard 等调研

## 1. 背景

江湖 Online 需要从自然语言需求和用户知识生成可编辑生产流程及 Agent 团队，在确定性流程中运行协作、对抗、裁判和人工节点，并保存可版本化的步骤产物、证据、缺陷、修订和裁决。

现有开源框架分别擅长图执行、Agent 团队、社会模拟、自动工作流生成、沙箱或可视化，但没有一个项目完整覆盖本产品的领域闭环。如果直接选择某个框架作为系统真相源，将产生以下风险：

- 框架会话或图状态与正式 Artifact 状态形成双重真相源；
- 产品 API、历史运行和数据库被框架对象绑定；
- 对抗、证据、缺陷、裁判和版本语义被迫映射为普通消息；
- 框架升级、维护状态或商业生态变化直接影响产品；
- 难以在相同 Task Contract 下比较不同模型、框架和协作策略。

## 2. 决策驱动因素

1. 正式产物独立于聊天并不可原地覆盖。
2. 运行、任务、Agent、模型、工具、知识和产物必须可追溯与复现。
3. 用户可以停止、修改、接管、重试和从检查点恢复。
4. 流程支持顺序、并行、条件、汇合和有限循环。
5. 多 Agent 协作和对抗必须具有显式协议、终止条件和质量门。
6. 平台必须支持单 Agent 与多 Agent 的同题对比实验。
7. MVP 采用 Python、FastAPI、PostgreSQL，并允许未来接入外部 Agent、MCP 和 A2A。
8. 框架必须可替换，框架故障不得破坏正式领域状态。

## 3. 备选方案

### 3.1 OpenClaw 作为核心运行时

拒绝。OpenClaw 的优势是个人助手 Gateway、多渠道、Agent 隔离、沙箱和子 Agent 委托，其正式状态仍以会话和任务树为中心，不适合承担生产 DAG、Artifact/Evidence/Defect/Decision 的唯一状态源。

### 3.2 单一多 Agent 框架作为核心领域模型

拒绝。Microsoft Agent Framework、LangGraph、CrewAI、AgentScope 和 ChatDev 均只能覆盖部分需求，直接绑定会限制产品领域表达和长期可替换性。

### 3.3 全部自研

暂不采用。长期可控，但 MVP 同时从零实现图执行、检查点、并行、取消、流式事件、Agent Worker 和沙箱，开发与可靠性风险过高。

### 3.4 领域运行时 + 可插拔执行适配层

接受。

## 4. 决策

系统采用两级编排：

```text
一级：江湖 Online 领域 Orchestrator
  - Workflow/Task 状态机
  - Artifact/Evidence/Defect/Revision/Decision
  - Version/Policy/Budget/Gate/Evaluation
  - 幂等、取消、重试、恢复和人工介入

二级：Agent Execution Adapter
  - Native LLM
  - LangGraph 或 Microsoft Agent Framework
  - AgentScope Worker
  - OpenClaw/A2A 外部 Agent
  - 未来其他框架
```

PostgreSQL 中的领域对象是唯一真相源。任何外部框架只接受平台下发的任务契约，返回候选产物和标准事件，无权直接：

- 推进全局 Workflow 状态；
- 将普通消息标记为正式产物；
- 覆盖历史产物或裁决；
- 绕过 Tool Gateway、知识权限、预算和人工审批；
- 将自身 Checkpoint 视为平台恢复点。

## 5. 框架选型

### 5.1 MVP 主路径

| 层 | 选择 | 说明 |
| --- | --- | --- |
| Web | Vue 3 + TypeScript + Vite | 延续现有实现 |
| API | FastAPI + Pydantic | 结构化 API、异步与 SSE 友好 |
| 数据库 | PostgreSQL | 领域状态、版本、事件和审计 |
| 队列 | Redis + Python Worker | 原型后在 Dramatiq、ARQ、RQ 等方案中确认 |
| 对象存储 | 本地目录抽象，兼容 S3 | 原文、附件和大 Artifact |
| 实时 | SSE 优先，必要时 WebSocket | 事件推送和断线恢复 |
| 模型接入 | 自研 Model Gateway | 统一结构化输出、成本、重试和供应商适配 |
| Agent 执行 | Native Adapter 首先实现 | 降低首个闭环依赖 |
| 图执行 POC | LangGraph 与 Microsoft Agent Framework 二选一验证 | 只用于二级局部编排或辅助一级执行 |
| Agent Worker POC | AgentScope | 重点验证事件、团队、权限和沙箱 |
| 外部 Agent | OpenClaw Adapter 后置 | P1 或 POC，不进入 MVP 核心闭环 |

### 5.2 研究参考，不直接作为核心依赖

| 项目 | 借鉴内容 |
| --- | --- |
| ChatDev 2.0 | Workflow Canvas、YAML、运行日志、中间 Artifact、HITL |
| MetaGPT | SOP、岗位职责、阶段产物和产品需求到开发方案 |
| EvoAgentX | 从目标生成 Workflow/Agent、评价和演化接口 |
| GEAR | 框架无关 Schema、静态校验和生成适配实现 |
| GAIA Blackboard | Task/Artifact/Evidence/Signal 生产黑板、租约和冲突任务 |
| CAMEL | Workforce、Critic、Judge Committee、Agent Society |
| Consensus Pipeline | 需求访谈、动态部门、有限辩论、逐主张证据和置信度 |
| GPTSwarm/AgentPrune | 拓扑与通信优化、削减无效消息 |
| MiroFish/OASIS | Persona、关系、环境、江湖视图和大规模仿真 |

AutoGen 进入维护模式，不作为新项目长期主依赖；相关模式优先在 Microsoft Agent Framework 中验证。

## 6. 强制架构边界

### 6.1 Agent Execution Port

所有执行器必须实现等价能力：

```python
class AgentExecutionPort(Protocol):
    async def start(self, request: AgentRunRequest) -> ExternalRunRef: ...
    async def cancel(self, run: ExternalRunRef) -> CancelResult: ...
    async def events(self, run: ExternalRunRef, after_cursor: str | None): ...
    async def result(self, run: ExternalRunRef) -> AgentRunResult: ...
    async def health(self) -> AdapterHealth: ...
```

### 6.2 输入契约

`AgentRunRequest` 必须包含：

- Project、Run、Task、Attempt 和 Trace 标识；
- 节点目标、任务类型和完成条件；
- 输入 Artifact Version 引用；
- 输出 JSON Schema；
- Agent Snapshot；
- Context Manifest；
- Knowledge Binding；
- Tool Binding 和权限；
- 模型与预算；
- 超时、取消、重试和沙箱策略；
- 幂等键。

### 6.3 输出契约

`AgentRunResult` 必须包含：

- 明确的终止状态；
- 结构化 Candidate Artifact；
- Evidence 引用；
- 公开理由摘要；
- 模型、Token、成本和时延；
- 工具调用摘要；
- 外部运行标识和版本；
- 可识别的错误类型。

只有通过 Schema、证据和质量门校验后，Candidate Artifact 才能转为正式 Artifact Version。

### 6.4 统一事件

所有执行器至少映射以下事件：

- `execution.accepted`
- `execution.started`
- `agent.message_published`
- `tool.started`
- `tool.completed`
- `evidence.attached`
- `candidate.submitted`
- `execution.blocked`
- `execution.failed`
- `execution.cancelled`
- `execution.completed`

## 7. P0 编排策略

MVP 支持：

- 确定性转换和校验；
- 单 Agent；
- 并行专家；
- 父子任务委托；
- 类型化 Handoff；
- 提案—评审—修订；
- 红队—回应—复测；
- 有限轮次辩论；
- 独立 AI 裁判；
- 人工输入、批准、否决和接管；
- 条件分支、汇合和有限返工。

自由 Swarm、大规模 Agent 社会和在线自演化不进入 P0。

## 8. 选型验证门禁

LangGraph、Microsoft Agent Framework、AgentScope 或其他框架只有同时满足以下门禁，才可进入 MVP 主路径：

1. 不要求公开 API 使用框架原生对象。
2. 进程重启后能够恢复或由平台安全重试。
3. 取消后不再提交合格正式产物。
4. 重试不会产生重复 Artifact Version。
5. 结构化输出失败可明确识别。
6. 事件可完整映射到平台协议。
7. 工具、知识、文件和网络权限可强制限制。
8. 能记录模型、Token、时延、错误和外部运行标识。
9. 同一 Task Contract 可切换为 Native Adapter。
10. 许可证和本地部署方式可接受。

## 9. 结果与影响

正面影响：

- 产品领域模型保持稳定；
- 可逐步引入成熟框架能力；
- 能够比较框架、模型和协作策略；
- 外部 Agent 故障与正式状态隔离；
- 支持未来 MCP、A2A 和多运行时。

代价：

- 需要维护执行适配协议；
- 平台与外部框架存在两级运行标识；
- 取消、恢复和错误语义需要统一转换；
- 首版必须实现最小 Native Adapter 作为基线和降级路径。

## 10. 后续行动

1. 根据系统需求定义 `AgentRunRequest`、`AgentRunResult` 和事件 Schema。
2. 实现 Native Adapter 端到端闭环。
3. 用同一红队评审任务验证 LangGraph、Microsoft Agent Framework 和 AgentScope。
4. 形成图执行框架的第二个 ADR。
5. OpenClaw 只进行外部 Agent/沙箱执行 POC。
6. 任何自动生成或演化 Workflow 在发布前必须静态校验并由平台版本化。

## 10.1 三类工程能力的归属补充

江湖 Online 明确采用 Harness Engineering、Loop Engineering 和 Graph Engineering，但三者属于一级领域运行时，而不是某个二级 Adapter：

- Harness：平台生成不可变执行快照，Adapter 只负责映射和执行；
- Loop：平台维护进展、Checkpoint、停滞检测、恢复、预算和终态；
- Graph：平台维护执行图、知识/社会图和生产溯源图的 Schema、版本、编译和查询。

LangGraph、Microsoft Agent Framework、AgentScope、OpenClaw 等可以贡献局部实现能力，但其原生 graph、checkpoint、session 或 memory 不得成为平台唯一真相源。详细设计见 `../04-design/harness-loop-graph-engineering.md`。

## 11. Grill Me 后的补充决策

以下内容于 2026-07-27 经用户逐项确认，作为本 ADR 的组成部分：

### 11.1 真实运行与裁判

- MVP 必须使用真实 LLM、真实并行 Agent、真实 Artifact 和真实代码执行完成验收。
- Mock/Simulator 只用于测试和降级。
- MVP 可以只配置一个模型；裁判仍必须具有独立 Agent 身份、独立上下文和独立 Prompt，并标记同模型裁判状态。

### 11.2 需求编译与从零生成

```text
用户自然语言与知识
-> 自适应 Grill Me
-> RequirementContract
-> 动态 OutputContract
-> 从零生成 Workflow 和 Agent
-> 静态校验与最多 3 次自动修复
-> 自动运行
```

- Workflow Generator 自身必须使用版本化规范、标准 Prompt、节点能力、Artifact Contract 和 Policy。
- 平台不提供固定流程作为首次生成前提。
- 平台预置生产方法、行业和角色能力知识，作为生成参考而不是必选模板。
- 成功运行后可以沉淀场景包，供后续选择、共享和市场分发。
- 平台固定 Artifact 基础协议；具体最终产物由每次 Run 的 OutputContract 动态定义。

### 11.3 真实软件交付能力

- 当 OutputContract 要求软件交付时，系统必须生成真实可运行、可测试的 Demo，而不是只生成文档。
- 每个编码 Task 使用独立 Git Worktree/工作副本和沙箱。
- 构建、启动、测试、扫描和代码变更都必须形成可追溯 Artifact。
- Agent 不能直接修改主工作区；应用 Patch/Commit Candidate 需要用户批准。

### 11.4 自动运行与资源约束

- 静态校验通过后立即运行低风险节点。
- 高风险外部写操作必须暂停审批。
- 默认最多 5 个并发 Agent、3 轮辩论、单节点 10 分钟、单 Run 60 分钟。
- 模型配置具有费用或 Token 上限，耗尽后进入 `budget_exhausted`。
- Agent 可在节点策略允许时动态派生新 AgentInstance，但不得提升权限。

### 11.5 知识与证据

- MVP 支持本地文档与网页搜索。
- 网页通过统一 Search/Fetch Gateway 获取，并保存 URL、抓取时间、引用片段和校验值。
- 搜索摘要不能直接作为正式 Evidence。
- 知识冲突不得静默合并，必须进入生产黑板并触发验证或用户裁决。

### 11.6 公共场景包市场

- 本地应用保持单用户、无登录，但支持匿名浏览、搜索和安装公共场景包。
- 发布通过独立市场服务、CLI 或 Git 审核流程。
- 普通场景包只包含声明式内容；可执行代码作为独立插件发布。
- 插件必须经过签名、扫描、授权并在沙箱运行。
- 所有安装、权限、文件、工具、网络和代码执行保留操作日志。
- 场景包不得自动升级或改变历史 Run；升级由用户查看差异后手动完成。

### 11.7 数据库、知识图谱与知识库参考 MiroFish

知识与图谱子系统参考 MiroFish 的以下链路：

```text
原始资料
-> 文本解析与分块
-> Ontology 生成
-> 实体、关系与证据图谱
-> Persona/Agent 生成
-> 运行行为与记忆增量写回
-> Report/Judge Agent 检索、采访和生成报告
```

采用的设计思想：

- 从当前需求和资料动态生成领域 Ontology；
- 实体、关系和 Agent Persona 尽可能关联原文 Evidence；
- 图谱同时服务 Workflow/Agent 生成、运行上下文、江湖视图和最终追溯；
- 运行行为先写入 Run Memory，经过证据、冲突和审批后才能进入长期知识；
- Report/Judge Agent 可以查询图谱、全景检索并采访参与 Agent；
- 知识图谱与生产 Artifact、Defect 和 Decision 建立关联。

不直接照搬的部分：

- 不把 Zep Cloud 作为不可替换的核心依赖；
- 不使用 JSON、JSONL、SQLite、目录文件分别承担正式领域状态；
- 不把社交媒体模拟环境作为通用生产运行时；
- 不允许模拟行为未经审核直接污染长期可信知识。

数据库和知识服务采用分层架构：

```text
PostgreSQL
  - 领域对象、版本、权限、事件、证据元数据
  - Entity/Relation 关系表
  - pgvector 或可替换向量接口

Artifact Storage
  - 原始文档、网页快照、大型 Artifact、代码与运行证据

Knowledge Graph Service
  - Ontology、实体、关系、时间和来源查询
  - MVP 从 PostgreSQL 关系表投影
  - 后续可替换为 Neo4j、Nebula、Zep 或其他图后端
```

无论使用何种图后端，PostgreSQL 中的领域版本、Evidence 引用和 Artifact 来源链仍是正式真相源。

### 11.8 长期操作型 Agent 与 OpenClaw

平台支持可跨 Run 复用的长期拟人 Agent。它们可以拥有独立外部身份、渠道账号、Skills、工具、沙箱、专业 Lane、Standing Orders 和受限后台子 Agent。

OpenClaw 定位调整为长期操作型 Agent 的优先 POC Adapter，而不是核心 Workflow 运行时：

- 江湖 Online 负责 Agent 选拔、Workflow、Harness、Loop、权限决策、Artifact 和 Judge；
- OpenClaw 负责长期身份装载、多渠道、外部账号、工具、沙箱、后台委托和真实操作；
- 所有操作结果返回平台形成 Evidence 和 CandidateArtifact；
- OpenClaw Session、Binding、Gateway 状态和 announce 不得成为正式生产状态；
- 外部写操作必须经过平台审批、幂等、结果确认和补偿协议。

详细设计见 `../04-design/operational-agent-and-openclaw-adapter.md`。
