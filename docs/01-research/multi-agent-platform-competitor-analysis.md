# 多 Agent 平台竞品与行业实践调研

> 调研日期：2026-07-24  
> 调研目的：理解主流多 Agent 产品和框架如何处理协作编排、知识、运行治理与平台化建设，为 Agent Arena 的产品边界和架构取舍提供依据。  
> 结论状态：研究建议，尚未全部转化为正式架构决策。

## 1. 调研范围与证据等级

本轮覆盖以下代表性方案：

| 方案 | 类型 | 主要观察点 |
| --- | --- | --- |
| 阿里云开发者社区文章 | 架构经验文章 | 路由、委托、辩论、群体四类协作模式 |
| 阿里云百炼 | 商业低代码平台 | Agent、工作流、知识库、MCP 与可视化编排 |
| Microsoft AutoGen | 开源多 Agent 框架与 Studio | 对话团队、GraphFlow、事件运行时、分布式扩展 |
| LangGraph | 开源 Agent 编排框架 | 状态图、上下文工程、Supervisor、Handoff 与持久执行 |
| Google ADK | 开源 Agent 开发套件 | 确定性工作流 Agent 与协作 Agent 的组合 |
| CrewAI | 开源框架与企业平台 | Crew、Flow、角色化 Agent、知识、记忆、治理 |
| Amazon Bedrock Agents | 云服务 | Supervisor/Collaborator、知识库、工具、Guardrail、权限 |
| OpenAI Agents SDK | Agent 开发 SDK | Agent-as-tool、Handoff、Guardrail、Session 与 Trace |
| Dify | 开源应用开发平台 | 可视化工作流、知识库、日志和外部可观测集成 |

证据分级：

- **一级证据**：厂商或项目官方文档，用于确认具体能力。
- **二级证据**：厂商开发者社区中的用户文章，用于提炼经验和假设，不作为产品能力的唯一证据。
- **本项目推断**：结合各方案形成的设计建议，需要在 Agent Arena 的实验中验证。

用户提供的阿里云文章属于开发者社区投稿，页面注明“内容由用户发布，不代表阿里云官方立场”，且标注了 AI 辅助创作。因此本文只吸收其模式划分与工程假设，并用官方文档进行交叉核验。

## 2. 阿里云文章：四种协作模式

文章将多 Agent 集群协作归纳为四类：

### 2.1 路由 Routing

中心路由器识别任务意图，将任务交给最合适的专家 Agent。

- 拓扑：星型。
- 优点：结构简单、成本低、职责清楚。
- 适用：问题分类明确、一次转交即可完成的任务。
- 风险：中心路由器成为瓶颈；连续转交会造成上下文损失和额外延迟。

### 2.2 委托 Delegation

管理 Agent 将复杂目标拆成子任务，分派给多个执行 Agent，再汇总结果。

- 拓扑：树型或有向任务图。
- 优点：支持任务分解、并行执行、分阶段验收。
- 适用：边界清晰、交付物可验收的长任务。
- 风险：管理 Agent 的规划错误会传递到全局；需要任务契约、状态恢复和人工介入。

### 2.3 辩论 Debate

提案方、质疑方和裁判围绕同一决策进行有限轮次交锋。

- 拓扑：三角形或多方评审结构。
- 优点：暴露单 Agent 的盲区，适合高风险判断。
- 适用：方案评审、风险分析、合规审查、主观性较高的决策。
- 风险：无限争论、立场趋同、裁判偏置、成本快速增加。
- 工程要求：证据锚点、最大轮次、终止条件、独立裁判和可解释裁决。

### 2.4 群体 Swarm

Agent 不完全依赖中心管理者，而是读取共享环境中的信号，按局部规则协同。

- 拓扑：网状或共享环境。
- 优点：适应性、容错性和涌现式分工较强。
- 适用：目标模糊、环境动态、需要异步探索的任务。
- 风险：结果难预测、难审计、激励不相容、收敛困难。

### 2.5 对 Agent Arena 的直接启示

四种模式不应做成四套互不相容的引擎，而应成为统一运行时上的四类**编排策略**：

```text
Workflow Definition
  + Agent Society
  + Context Policy
  + Coordination Strategy
  + Termination Policy
  + Evaluation Policy
```

Agent Arena 第一阶段应优先支持路由、委托、有限轮次辩论。群体模式可以先保留协议和实验接口，暂不作为 P0 的生产能力。

## 3. 各家是怎么做的

### 3.1 阿里云百炼：低代码节点编排

百炼把应用分为 Agent、Workflow 和高代码应用。工作流通过可视化节点组织大模型、知识库、MCP、API、条件分支和应用组件；已发布的 Agent 也能作为工作流组件被复用。

值得借鉴：

- 固定知识库和动态知识库均可配置。
- 知识检索结果包含片段、文档、页码、相似度等证据信息。
- Agent、Workflow 可以发布为组件，利于复用。
- 节点级错误分支、变量映射和运行调试降低了业务使用门槛。

局限或空白：

- 产品核心仍是应用和节点编排，不突出“社会规则、对抗协议、组织学习”。
- 多 Agent 的社会关系和质量竞争机制不是主要建模对象。

### 3.2 Microsoft AutoGen：从对话团队到事件运行时

AutoGen 分为 Studio、AgentChat、Core 和 Extensions：

- Studio 用于无代码原型。
- AgentChat 提供 RoundRobin、Selector、Swarm、GraphFlow 等团队模式。
- Core 是事件驱动、可分布式的多 Agent 运行时。
- Extensions 提供 MCP、代码执行器和 gRPC Worker 等扩展。

GraphFlow 用有向图表达顺序、并行、条件、汇合和带退出条件的循环。官方建议：自由对话足够时使用简单团队，需要确定顺序、分支和循环时再使用图工作流。

值得借鉴：

- “轻量团队”和“严格工作流”并存。
- Agent 交互是一等事件，可流式观察。
- 图中循环必须具备退出条件。
- UI 原型层与可扩展运行时分层。

### 3.3 LangGraph：状态图与上下文工程

LangGraph 将多 Agent 的核心问题定义为上下文工程：每个 Agent 在每一步应该看到什么。其常见模式包括：

- Subagents：主 Agent 把子 Agent 当作工具调用。
- Handoffs：Agent 之间转移控制权。
- Skills：按需加载专业知识和指令。
- Router：先分类，再路由到一个或多个专家。
- Custom workflow：在状态图中混合确定性逻辑与 Agent 自主行为。

Supervisor 可以继续管理子 Supervisor，形成层级组织；检查点和 Store 分别承载运行内状态与长期记忆。

值得借鉴：

- 编排边之外，还要显式配置上下文输入和输出。
- 子 Agent 隔离上下文可以减少 token 消耗与信息污染。
- 每次 Handoff 都应定义移交的数据，而不是默认传递全部历史。
- 持久化、人工介入和恢复能力属于运行时核心，不是外围功能。

### 3.4 Google ADK：确定性骨架加自主节点

Google ADK 同时提供 LLM Agent 和工作流 Agent。工作流 Agent 可按顺序、并行和循环执行子 Agent，整体控制逻辑不由模型决定，因此更可预测。自定义 Agent 可实现任意控制流；新版也进一步提供图工作流。

值得借鉴：

- 用确定性结构约束生产流程。
- 只在需要判断、规划或创造的节点使用 LLM 自主性。
- 顺序、并行、循环应成为 Workflow Studio 的原生结构。
- 循环需要最大迭代次数或明确的退出信号。

### 3.5 CrewAI：Crew 与 Flow 双层模型

CrewAI 明确区分：

- Crew：角色化 Agent 组成的自治团队，适合开放问题。
- Flow：事件驱动、带状态、可持久化和恢复的确定性流程。
- 混合方式：Flow 管理主流程，在局部节点中调用 Crew。

其平台能力还覆盖工具、知识、记忆、结构化输出、Guardrail、回调、人工介入、可观测性、部署和 RBAC。

值得借鉴：

- “流程中嵌入自治团队”比把所有节点都做成 Agent 更符合生产实践。
- Agent Blueprint 应包含角色、目标、工具、知识、委托权限和输出契约。
- 企业平台除了运行，还必须处理部署环境、权限和触发器。

### 3.6 Amazon Bedrock：受治理的层级协作

Bedrock Agents 的经典多 Agent 模式是一个 Supervisor 关联多个 Collaborator。Supervisor 负责计划、路由和结果汇总，Collaborator 负责专业子任务。每个 Agent 都可拥有工具、Action Group、知识库和 Guardrail，并由 IAM 控制调用权限。

值得借鉴：

- Agent 职责应尽量不重叠，否则 Supervisor 难以稳定路由。
- 每个 Agent 都要有独立工具、知识与安全边界。
- 调用链应记录发起者、协作者、版本、会话和工具执行。
- Agent 的发布版本与运行别名应分离。

注意：AWS 官方已说明 Bedrock Agents Classic 将在 2026-07-30 起不再向新客户开放，新的扩展方向转向 AgentCore。这个变化也说明平台不宜绑定单一云厂商的 Agent 抽象。

### 3.7 OpenAI Agents SDK：Handoff 是带契约的工具调用

OpenAI Agents SDK 将 Handoff 表示为一种工具调用。它可配置目标 Agent、工具描述、结构化输入、回调和输入过滤器。

值得借鉴：

- Agent 间移交必须有类型化载荷。
- Handoff 应记录“为什么移交、交给谁、传了什么、接收方看到了什么”。
- 输入过滤器可以防止把不相关或敏感上下文传给下一个 Agent。
- Agent-as-tool 和 Handoff 应视为两种不同语义：前者返回控制权，后者转移控制权。

### 3.8 Dify：应用生产与运维体验

Dify 的优势主要在应用搭建、知识库、工作流 UI、日志和外部可观测集成。其文档展示了与 Phoenix、Arize、W&B Weave 和阿里云 ARMS 等平台的集成。

值得借鉴：

- 运行日志必须面向业务用户可读。
- 可观测数据应兼容 OpenTelemetry 或可导出到外部平台。
- 知识、工作流、发布与监控需要形成完整产品闭环。

## 4. 横向对比

| 维度 | 百炼 | AutoGen | LangGraph | ADK | CrewAI | Bedrock | OpenAI SDK | Dify |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 可视化编排 | 强 | Studio 原型 | 依赖配套产品 | 开发者为主 | 平台化增强中 | 控制台 | 无内置完整 Studio | 强 |
| 确定性工作流 | 强 | GraphFlow | 强 | 强 | Flow | 有限 | 代码实现 | 强 |
| 自主团队 | Agent 群组 | 强 | 强 | 强 | Crew | Supervisor 模式 | Handoff/Tool | 较弱 |
| 对抗/辩论 | 非核心 | 可组合 | 可组合 | 可自定义 | 可组合 | 非核心 | 可组合 | 非核心 |
| 知识库 | 强 | 需集成 | 需集成 | 组件化 | 内置概念 | 强 | 需集成 | 强 |
| 长短期记忆 | 应用记忆 | 支持 | 强 | Session/Memory | 强 | Session/KB | Session | 会话为主 |
| 人工介入 | 节点能力 | 支持 | 强 | 支持 | 支持 | 支持 | 支持 | 支持 |
| Trace/评测 | 调试与平台能力 | 事件流 | LangSmith 生态 | Eval 能力 | 可观测生态 | Trace | 内置 Trace | 日志及外部集成 |
| 权限治理 | 云平台能力 | 自建 | 自建 | 自建/云 | 企业版 | IAM/Guardrail | 自建 | Workspace 权限 |
| 社会体系建模 | 弱 | 团队模式 | 图/层级 | Agent 树/图 | 角色团队 | 层级团队 | 代码级 | 弱 |

## 5. 行业共识

### 5.1 多 Agent 不等于多角色聊天

真正的多 Agent 系统至少需要：

- 独立角色、目标、工具和知识边界。
- 明确的任务或控制权转移。
- 可观察的消息、状态和产物。
- 终止、失败、重试与人工接管机制。
- 可验证的输出契约和质量标准。

### 5.2 自主性必须嵌入确定性骨架

友商普遍同时提供工作流与 Agent。生产系统中的通用结构是：

```text
确定性流程骨架
  -> 自主规划或专业执行节点
  -> 规则/模型/人工质量门
  -> 可恢复状态
  -> 可审计产物
```

全自主群聊容易演示，但难以控制成本、复现故障和完成验收。

### 5.3 上下文边界比 Agent 数量更重要

Agent 的效果取决于它收到的任务、证据、历史、工具结果和其他 Agent 产物。平台应把 Context Policy 建模为一等对象，支持：

- 全量历史、最近消息、摘要、指定产物四种传递方式。
- 知识空间与 Agent 的显式绑定。
- Handoff 输入过滤。
- 敏感字段脱敏与权限校验。
- 上下文 token 预算。

### 5.4 运行治理是平台的核心价值

各家生产能力集中在：

- 状态持久化与恢复。
- Trace、日志、成本和时延。
- Agent/Workflow 版本化。
- Guardrail 与权限。
- 人工审批和接管。
- 离线评测与回归测试。

因此 Agent Arena 不应只做设计器，必须同时做“运行控制台”和“评估实验室”。

## 6. Agent Arena 应该怎么做

### 6.1 产品定位

Agent Arena 不复制某一家通用 Agent Builder，而应聚焦：

> 面向组织生产场景的多 Agent 社会设计、协作对抗运行与持续评估平台。

差异化不在于节点更多，而在于把以下对象做成一等公民：

- Agent Blueprint
- Society Template
- Coordination Strategy
- Debate Protocol
- Context Policy
- Evidence Policy
- Evaluation Suite
- Learning Record

### 6.2 P0 能力

1. **Agent Library**：配置角色、目标、模型、工具、知识、权限、输出契约和版本。
2. **Knowledge Hub**：导入资料、建立知识空间、检索调试、展示证据来源。
3. **Society Designer**：配置 Supervisor、专家、挑战者、裁判及其关系。
4. **Workflow Studio**：支持顺序、并行、条件、循环、路由、委托、辩论和人工节点。
5. **Live Arena**：实时展示任务、消息、Handoff、工具调用、证据、产物、成本和状态。
6. **Evaluation Lab**：用规则、裁判模型和人工评分比较单 Agent 与多 Agent。
7. **Template Library**：保存可复用的 Agent、社会、工作流和评测模板。

### 6.3 统一运行语义

建议定义七类核心事件：

| 事件 | 含义 |
| --- | --- |
| `task.created` | 创建任务和验收契约 |
| `task.delegated` | 委托子任务，调用方保留控制权 |
| `control.handed_off` | 将当前控制权转交给另一个 Agent |
| `message.published` | Agent 发布观点、反馈或问题 |
| `evidence.attached` | 将可追溯证据绑定到主张或产物 |
| `artifact.submitted` | 提交结构化交付物 |
| `decision.rendered` | 裁判、规则或人工作出决策 |

任何编排策略都应映射为这些事件与状态转换，以便统一观察、回放和评估。

### 6.4 首批编排策略

| 策略 | P0/P1 | 实现建议 |
| --- | --- | --- |
| 顺序/并行/条件 | P0 | 确定性图执行 |
| 路由 | P0 | 规则路由优先，模型路由可选 |
| 委托 | P0 | 结构化任务契约、父子任务、汇总节点 |
| 有限轮次辩论 | P0 | 提案者、挑战者、裁判、证据约束、最大轮次 |
| Handoff | P0 | 类型化载荷、输入过滤、控制权记录 |
| 人工审批/接管 | P0 | 暂停、恢复、修改、否决 |
| 群体协作 | P1/P2 | 共享环境、异步信号、预算与收敛实验 |

## 7. 不建议照搬的做法

- 不把所有节点都包装成 Agent；确定性转换和校验应使用普通节点。
- 不用共享完整聊天历史代替上下文策略。
- 不只用“最终答案看起来不错”评价效果。
- 不把裁判 Agent 当作绝对真值；需要规则、证据和人工抽检。
- 不先做复杂 Swarm；先把路由、委托、辩论的运行闭环做扎实。
- 不绑定单一模型、云厂商或 Agent 框架。
- 不让演示案例反向限定平台领域模型。

## 8. 下一步研究与验证

1. 将本报告的 P0 能力映射到现有领域模型，找出缺失字段和对象。
2. 定义 `AgentBlueprint`、`ContextPolicy`、`CoordinationStrategy` 和 `EvaluationSuite` 的 JSON Schema。
3. 为路由、委托、辩论各制作一个最小实验，记录效果、token、时延和失败类型。
4. 对比单 Agent 与多 Agent，验证“增加 Agent 是否真的改善结果”。
5. 调研 MiroFish/OASIS 的大规模社会模拟机制与本平台生产工作流运行时之间的适配边界。
6. 把确定的架构取舍分别写入 ADR，而不是让本研究文档直接充当最终决策。

## 9. 参考资料

- [阿里云开发者社区：多Agent集群协作架构设计](https://developer.aliyun.com/article/1734661)
- [阿里云百炼：应用类型介绍](https://help.aliyun.com/zh/model-studio/application-introduction)
- [阿里云百炼：工作流应用](https://help.aliyun.com/zh/model-studio/workflow-application/)
- [Microsoft AutoGen 官方文档](https://microsoft.github.io/autogen/stable/index.html)
- [Microsoft AutoGen GraphFlow](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/graph-flow.html)
- [LangChain/LangGraph Multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent)
- [LangGraph Supervisor API](https://langchain-ai.github.io/langgraphjs/reference/modules/langgraph-supervisor.html)
- [Google ADK Multi-agent Systems](https://adk.dev/agents/multi-agents/)
- [Google ADK Workflow Agents](https://google.github.io/adk-docs/agents/workflow-agents/)
- [CrewAI 官方文档](https://docs.crewai.com/)
- [Amazon Bedrock Multi-agent Collaboration](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html)
- [OpenAI Agents SDK Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [Dify Logs](https://docs.dify.ai/en/cloud/use-dify/monitor/logs)
- [Dify Observability Integrations](https://docs.dify.ai/en/cloud/use-dify/monitor/integrations/integrate-phoenix)

