# OpenClaw 与多 Agent 技术方案选项分析

> 日期：2026-07-27
> 输入：`jianghu-online-prd-v1.0.md`、`user-requirements-v2.md`、现有竞品调研与候选系统架构
> 目的：在系统需求分析阶段，明确 OpenClaw 能力边界、补充友商方案，并形成可验证的技术路线选项。
> 结论状态：候选方案，原型验证后转为 ADR。

## 1. 结论摘要

江湖 Online 不宜直接以 OpenClaw 作为核心生产流运行时，也不宜把某个通用 Agent 框架的对象模型直接暴露为产品领域模型。

推荐采用：

> **自研领域运行时 + 可插拔 Agent 执行适配层 + OpenClaw/其他框架作为外部 Agent 或能力参考。**

理由：

1. 当前 PRD 的核心不是“多个助手一起聊天”，而是可编辑 DAG、正式步骤产物、证据链、对抗缺陷、修订、裁判、人工介入、版本复现和单/多 Agent 对比评测。
2. OpenClaw 强项是本地优先 Gateway、多渠道接入、Agent 隔离、子 Agent 委托、工具权限和沙箱；这些能力值得借鉴或通过适配器接入。
3. LangGraph、AutoGen、CrewAI 等可降低局部编排开发量，但不能代替江湖 Online 的领域状态机、Artifact/Evidence/Defect/Decision 模型与运行审计。
4. MVP 应优先保证“确定性流程骨架中嵌入自主 Agent 节点”，而不是先追求自由 Swarm。

## 2. 当前 PRD 对运行时的刚性要求

从 PRD 提炼出的 P0 技术约束如下：

| 需求域 | 不可缺少的运行语义 |
| --- | --- |
| 流程生成 | 从自然语言和知识生成可编辑、可校验、可版本化的有向任务图 |
| 节点类型 | 确定性、单 Agent、多 Agent 协作、多 Agent 对抗、裁判、人工、汇合 |
| 正式产物 | 每个完成节点产生不可原地覆盖的 Artifact Version，并作为下游显式输入 |
| 对抗闭环 | 提案、攻击、缺陷、回应、修订、复测、裁决均为结构化对象 |
| 证据追溯 | 结论和产物可追溯至来源、知识版本、上游产物、Agent、模型和工具调用 |
| 运行控制 | 启动、暂停、恢复、停止、取消、重试、返工和人工接管 |
| 安全治理 | Agent 级知识、工具、文件、网络、模型和预算权限；高风险动作审批 |
| 可观察性 | 任务、消息、Handoff、工具、证据、产物、缺陷、门禁、成本和时延事件流 |
| 可复现性 | 固定 Workflow、Agent、Prompt、模型、知识、工具和输入版本后可重放 |
| 价值证明 | 同输入下比较单 Agent、协作和对抗模式的质量、风险、成本、时延与稳定性 |

因此，聊天历史不能充当正式状态，Agent 的自然语言回复也不能直接等同于节点完成。

## 3. OpenClaw 多 Agent 方案拆解

### 3.1 产品定位

OpenClaw 官方将自身定位为运行在用户自有设备上的个人 AI 助手。Gateway 是会话、渠道、工具和事件的控制平面，能够连接 WhatsApp、Telegram、Slack、Discord、飞书等渠道。

它的多 Agent 能力包含两个不同层次。

### 3.2 多 Agent 路由：多个隔离 persona 共用一个 Gateway

每个 Agent 拥有独立的：

- Workspace，包括 `AGENTS.md`、`SOUL.md`、`USER.md` 和本地文件；
- `agentDir`，保存认证、模型注册和 Agent 配置；
- SQLite 会话与历史；
- 渠道账号和路由状态；
- 可覆盖的技能、工具和沙箱策略。

Gateway 通过 `bindings` 按渠道、账号、会话对端、群组等条件，把入站消息确定性地路由到一个 Agent。匹配采用“更具体规则优先”，同层规则按配置顺序处理。

这类能力解决的是：

- 多助手/多身份隔离；
- 多渠道入口路由；
- 独立认证和会话；
- 一个 Gateway 托管多个长期 Agent。

它本身不等于多个 Agent 围绕一个生产目标协同完成正式交付物。

### 3.3 子 Agent：父 Agent 动态委托隔离后台任务

OpenClaw 的 `sessions_spawn` 可从当前 Agent 运行中派生后台子 Agent：

- 非阻塞启动，立即返回 run id 和子会话标识；
- 子 Agent 默认上下文隔离，也可选择 fork 父会话上下文；
- 可选择目标 Agent、模型、工作目录、沙箱要求和清理策略；
- 完成后通过 announce 链回传给直接父 Agent；
- 支持并行任务和有限嵌套；默认最大深度为 1，可配置为 2 形成“主 Agent → 编排子 Agent → 叶子 Worker”；
- 每个 Agent 可限制活跃子 Agent 数量，停止父任务可级联停止子任务；
- 子 Agent 默认不拥有消息和会话管理工具，降低越权和递归失控风险。

这是一种实用的树型委托模式，适合研究、编码、检索和相互独立的子任务。

### 3.4 沙箱与工具策略

OpenClaw 支持 Agent 级：

- 沙箱开关、作用域和工作区访问；
- 工具 profile、allow/deny 和按模型供应商覆盖；
- 独立认证存储；
- 沙箱父 Agent 不得派生为非沙箱子 Agent；
- 对 exec、browser、write、message 等工具实施不同权限组合。

对江湖 Online 最值得借鉴的是“权限由运行时强制执行，而不是只写在 Prompt 中”。

### 3.5 OpenClaw 与本项目的能力差距

| 江湖 Online 需要 | OpenClaw 当前重点 | 判断 |
| --- | --- | --- |
| 可编辑生产 DAG | 渠道路由、会话队列、父子派生 | 需自建 |
| Artifact Version | 以会话消息、文件和任务结果为主 | 需自建正式产物注册表 |
| Evidence/Claim 绑定 | 有会话历史和工具结果，但非业务证据模型 | 需自建 |
| 缺陷—修订—复测 | 无通用结构化闭环 | 需自建 |
| 辩论协议和独立裁判 | 可用子 Agent 组合实现，但不是原生领域对象 | 需在平台层实现 |
| 质量门禁 | 有运行安全约束，无 PRD 所需业务 Gate | 需自建 |
| 人工节点和流程回退 | 有会话交互与停止能力，不等同于工作流检查点 | 需自建 |
| 单/多 Agent 实验 | 无面向本产品的评测实验模型 | 需自建 |
| 多渠道个人助手 | 强 | 非 MVP 核心，可后续接入 |
| Agent 隔离、沙箱、工具权限 | 强 | 可借鉴或集成 |

结论：OpenClaw 更适合作为“可接入的 Agent 执行端/个人助手节点”和工程参考，而不是江湖 Online 的主编排内核。

## 4. 友商与开源方案补充对比

| 方案 | 核心抽象 | 优势 | 与本项目的主要差距/风险 | 推荐用途 |
| --- | --- | --- | --- | --- |
| OpenClaw | Gateway、Agent、Binding、Session、Sub-agent | 本地优先、多渠道、隔离、沙箱、父子委托 | 非生产 Artifact 工作流；委托以会话树为中心 | 外部 Agent、工具执行端、隔离与权限参考 |
| LangGraph | State、Node、Edge、Checkpoint、Store | 状态图、恢复、HITL、上下文控制、组合灵活 | 领域对象仍需自建；易让框架状态渗入产品 API | 首选底层编排候选之一 |
| AutoGen | AgentChat Team、GraphFlow、事件运行时 | 多 Agent 对话模式丰富、事件流、GraphFlow | GraphFlow 成熟度和 API 变化需验证；产物治理不足 | 辩论/群组模式原型 |
| CrewAI | Crew + Flow | 角色团队与确定性 Flow 分层清楚，上手快 | 深度定制、持久状态和领域映射需验证 | 快速验证委托和团队模式 |
| Google ADK | LLM Agent + Sequential/Parallel/Loop Workflow | 确定性工作流与自主节点组合明确 | 偏开发套件和 Google 生态；业务治理需自建 | 工作流语义参考/原型 |
| OpenAI Agents SDK | Agent-as-tool、Handoff、Guardrail、Session、Trace | Handoff 契约清晰，代码轻量，Trace 完整 | 无完整 DAG Studio 和业务持久化模型 | Model/Agent 执行适配器 |
| Microsoft Copilot Studio | Connected Agents、流程、知识、测试和治理 | 低代码、组织 Agent 复用、企业治理 | 商业平台绑定，难作为自研底座 | 产品体验与资产治理参考 |
| IBM watsonx Orchestrate | 主/协作 Agent、目录、A2A、控制平面 | 企业 Agent 目录、策略、监控和互操作 | 商业平台绑定、成本和部署约束 | Agent Registry/A2A 参考 |
| 阿里云百炼 | Agent、Workflow、知识库、MCP 节点 | 国内生态、低代码、知识和工作流完整 | 社会关系、对抗和正式产物不是核心 | UI、MCP 与知识接入参考 |
| Dify | App、Workflow、Knowledge、Logs | 产品成熟、可视化和运维体验强 | 多 Agent 社会与对抗语义弱 | Workflow Studio/日志体验参考 |

## 5. 技术路线选项

### 方案 A：以 OpenClaw 为核心运行时

做法：江湖 Online 负责 UI、PRD 解析和报告；每个角色映射为 OpenClaw Agent，节点通过会话、`sessions_spawn` 和 announce 执行。

优点：

- 很快获得 Agent 隔离、模型接入、工具、沙箱和子任务并行；
- 本地部署、多渠道和个人助手扩展能力强；
- 可直接复用其 Gateway 运维能力。

缺点：

- 生产流被迫映射为会话树，DAG、汇合、回退和质量门语义不自然；
- 正式产物、证据、缺陷和裁决仍要另建一套状态，产生双状态源；
- announce 是尽力交付，Gateway 重启可能丢失待回传工作，不满足正式产物强一致要求；
- Node/TypeScript 主运行时与现有 Python/FastAPI 技术栈形成双内核；
- OpenClaw 产品方向是个人助手，升级节奏可能与本项目领域目标不一致。

结论：不推荐作为核心底座。

### 方案 B：选用单一多 Agent 框架作为核心编排

做法：在 LangGraph、AutoGen 或 CrewAI 中选一个作为工作流真相源，并围绕它建设 API 和 UI。

优点：

- 原型速度快；
- 可复用图执行、Agent 团队、检查点或事件流；
- 社区示例和模型工具集成较多。

缺点：

- 框架状态和产品领域状态容易耦合；
- Artifact/Evidence/Defect/Decision、版本规则和评测仍需自建；
- 框架升级或抽象调整会影响产品 API 和历史运行；
- 同时满足严格 DAG、辩论、对抗和未来外部 A2A 时仍需较厚封装。

结论：可用于 MVP 加速，但必须通过反腐层隔离，不能让框架对象成为公开领域模型。

### 方案 C：自研领域状态机，不引入 Agent 编排框架

做法：使用 FastAPI、PostgreSQL、Redis Worker 和自研 Orchestrator；所有 Agent 调用通过统一执行接口完成。

优点：

- 完全贴合 PRD，运行、产物、证据和门禁只有一个真相源；
- 版本、幂等、恢复和回放可以按业务语义设计；
- 不绑定模型或框架。

缺点：

- 初期开发量最大；
- 图执行、检查点、并发、取消和人工介入容易重复造轮子；
- 如果边界设计不稳，MVP 周期风险较高。

结论：长期最可控，但不建议首版把所有基础设施都从零实现。

### 方案 D：领域运行时 + 可插拔执行适配层（推荐）

做法：

```text
江湖 Online 领域层
  - Workflow/Task 状态机
  - Artifact/Evidence/Defect/Revision/Decision
  - Version/Budget/Policy/Evaluation
            |
            v
Agent Execution Port
  - run_agent
  - delegate
  - handoff
  - cancel
  - stream_events
            |
   +--------+----------+-------------+
   |                   |             |
Native LLM Adapter  LangGraph Adapter  OpenClaw/A2A Adapter
```

领域数据库是唯一真相源。外部框架只执行受约束的 Agent 节点，返回结构化结果和事件，不拥有正式流程状态。

优点：

- 兼顾 MVP 速度和长期可控性；
- 可以先用轻量 Native Adapter，必要时在局部节点采用 LangGraph/AutoGen；
- OpenClaw 可作为远程 Agent 或受沙箱保护的执行端接入；
- 方便做同一任务在不同框架、模型和团队策略之间的对照实验。

代价：

- 必须较早定义稳定的执行端口、事件协议和结构化输出；
- 需要处理外部运行 id 与内部 Task Attempt 的映射；
- 取消、超时、重试和幂等必须由平台统一裁决。

结论：推荐。

## 6. 推荐目标架构

### 6.1 核心原则

1. PostgreSQL 中的领域状态是唯一真相源。
2. Orchestrator 决定节点何时可运行、完成、返工或终止；Worker/Agent 不直接推进全局状态。
3. Agent 输出先进入 Candidate Submission，经过 Schema、证据和质量 Gate 后才成为正式 Artifact Version。
4. 所有外部框架都通过 Adapter 接入，不能直接写正式产物和运行状态。
5. 事件先持久化，再通过 SSE 推送；大产物只推引用。
6. 默认上下文最小化，Handoff/Delegate 使用类型化载荷，不传完整聊天历史。
7. 权限在服务端、沙箱和工具网关执行，不依赖 Prompt 自律。

### 6.2 建议新增的核心接口

```python
class AgentExecutionPort(Protocol):
    async def start(self, request: AgentRunRequest) -> ExternalRunRef: ...
    async def cancel(self, run: ExternalRunRef) -> None: ...
    async def events(self, run: ExternalRunRef, after: str | None): ...
    async def result(self, run: ExternalRunRef) -> AgentRunResult: ...
```

`AgentRunRequest` 至少包含：

- `task_contract`：目标、输入 Artifact Version、输出 Schema、验收规则；
- `agent_snapshot`：角色、Prompt、模型、工具、知识、权限和预算版本；
- `context_manifest`：允许读取的消息、摘要、证据和产物引用；
- `execution_policy`：超时、重试、沙箱、幂等键和取消策略；
- `correlation`：project/run/task/attempt/trace 标识。

`AgentRunResult` 至少包含：

- 结构化候选产物；
- 引用的 Evidence；
- 公开解释摘要，不保存私有思维链；
- 工具调用与模型用量摘要；
- 完成、失败、阻断、取消或超时状态；
- 外部框架和运行版本信息。

### 6.3 首版编排策略

| 策略 | 实现方式 | 首版 |
| --- | --- | --- |
| 顺序/并行/条件/汇合 | 领域 DAG 确定性执行 | P0 |
| 路由 | 规则优先，模型分类作为候选并记录置信度 | P0 |
| 委托 | 父子 Task Contract，子任务并行，汇总节点验收 | P0 |
| Handoff | 显式责任转移、类型化载荷、上下文过滤 | P0 |
| 有限辩论 | 提案者—挑战者—回应者—裁判，固定轮次和证据要求 | P0 |
| 红蓝对抗 | 缺陷 Schema、严重度、证据、复现和修订关系 | P0 |
| 人工介入 | 输入、批准、否决、修改约束、接管 | P0 |
| Swarm | 共享环境、异步信号和收敛实验 | P2 |

## 7. 原型验证计划

不要先做大而全选型。建议用同一条“产品需求 → 技术方案”流程完成四个可替换原型。

### 7.1 POC-1：原生执行端口

- 单 Agent 根据需求产出结构化技术方案；
- 保存 Artifact、Evidence、模型用量和事件；
- 验证 Schema 失败、超时、取消和重试。

### 7.2 POC-2：LangGraph 或 AutoGen 局部团队适配

- 3 个 Agent：方案设计、红队攻击、裁判；
- 平台只向框架传 Task Contract；
- 框架输出必须转换为平台 Candidate Submission；
- 验证暂停恢复、事件映射、取消和幂等。

### 7.3 POC-3：OpenClaw 外部 Agent 适配

- 为两个 OpenClaw Agent 配置独立 workspace、session、工具和沙箱；
- 通过受控 API/CLI Adapter 发起任务，不让其直接写平台数据库；
- 验证隔离、并行子 Agent、回传、超时、Gateway 重启和失败补偿；
- 判断其适合作为长期 Agent、渠道入口还是工具执行节点。

### 7.4 POC-4：单 Agent 与多 Agent 对比

相同输入至少运行：

1. 单 Agent；
2. 设计 + 审查；
3. 设计 + 红队 + 修订 + 裁判。

记录：

- 验收规则通过率；
- 关键风险发现率与有效缺陷率；
- 证据覆盖率；
- 返工后缺陷关闭率；
- Token、费用、总时延和人工等待；
- 结构化输出失败率；
- 多次运行结果稳定性。

## 8. 选型门禁

候选框架只有满足以下条件才允许进入 MVP 主路径：

| 门禁 | 最低要求 |
| --- | --- |
| 领域隔离 | 不要求公开 API 使用框架原生对象 |
| 状态恢复 | 进程重启后可从平台 Task Attempt 恢复或安全重试 |
| 取消 | 用户停止后能够终止或隔离外部运行，且不会标记成功 |
| 幂等 | Worker/框架重试不产生重复正式 Artifact Version |
| 结构化输出 | 能稳定返回指定 Schema，失败可识别而非伪造空结果 |
| 事件映射 | 可映射 start/tool/message/artifact/error/end 等统一事件 |
| 安全 | 工具、知识、文件和网络权限可由平台强制约束 |
| 可观测 | 能获得模型、Token、时延、错误和外部 run id |
| 可替换 | 同一 Task Contract 可切换 Native、框架或远程 Agent Adapter |
| 许可证与部署 | 允许目标部署方式，依赖、升级和运维成本可接受 |

## 9. 系统需求分析阶段的建议决策

建议立即确认以下方向，并在 POC 后形成 ADR：

1. 采用方案 D：领域运行时 + 可插拔执行适配层。
2. MVP 不实现自由 Swarm，先实现确定性 DAG、委托、Handoff、有限辩论、红蓝对抗和人工介入。
3. OpenClaw 不作为主状态机；将其列为外部 Agent/渠道入口/隔离执行端候选。
4. LangGraph 作为首个图编排适配候选，AutoGen 作为对话团队/辩论模式对照候选；二者通过同一门禁实测后再决定是否进入主路径。
5. 先定义 `AgentRunRequest`、`AgentRunResult`、统一事件和 Artifact 提交协议，再选择框架。
6. 将“多 Agent 比单 Agent 更好”作为可量化验收，而不是默认假设。

## 10. 公开资料

- [OpenClaw 官方仓库](https://github.com/openclaw/openclaw)
- [OpenClaw Multi-agent routing](https://docs.openclaw.ai/concepts/multi-agent)
- [OpenClaw Sub-agents](https://docs.openclaw.ai/tools/subagents)
- [OpenClaw Multi-agent sandbox and tools](https://docs.openclaw.ai/tools/multi-agent-sandbox-tools)
- [OpenClaw Agent loop](https://docs.openclaw.ai/concepts/agent-loop)
- [LangGraph Multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent)
- [Microsoft AutoGen](https://microsoft.github.io/autogen/stable/index.html)
- [Google ADK Multi-agent Systems](https://adk.dev/agents/multi-agents/)
- [CrewAI Documentation](https://docs.crewai.com/)
- [OpenAI Agents SDK Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [Amazon Bedrock Multi-agent collaboration](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html)
- [阿里云百炼工作流应用](https://help.aliyun.com/zh/model-studio/workflow-application/)
- [Dify Documentation](https://docs.dify.ai/)
