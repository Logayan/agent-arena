# 与江湖 Online 相似的多 Agent 开源方案调研

> 调研日期：2026-07-27
> 目标：寻找与“需求驱动生成生产流程、多角色协作与对抗、步骤产物流转、人工介入、运行观察和评测”相近的开源项目。
> 证据：优先使用项目官方仓库和官方文档；Stars 为调研日附近的 GitHub 快照，只用于判断社区规模，不代表技术质量。

## 1. 总体结论

目前没有一个开源项目完整覆盖江湖 Online 的需求。最接近的能力分散在四类项目中：

| 类型 | 代表项目 | 与本项目最相关的部分 |
| --- | --- | --- |
| 生产级图工作流 | Microsoft Agent Framework、LangGraph、CrewAI、AgentScope | 持久执行、流程控制、HITL、权限、事件和恢复 |
| 可视化多 Agent 平台 | ChatDev 2.0、AutoGen Studio | 零代码流程、Agent 配置、运行日志、中间结果 |
| 角色化生产团队 | MetaGPT、ChatDev 1.0 | SOP、岗位分工、阶段交付物、审查与返工 |
| Agent 社会与模拟 | CAMEL、MiroFish、OASIS、AgentVerse | 人格、立场、环境、社会互动、辩论和涌现 |

最值得深入 POC 的组合是：

1. **Microsoft Agent Framework 或 LangGraph**：候选底层图执行与恢复机制；
2. **AgentScope**：候选 Agent 执行服务、事件、权限与沙箱参考；
3. **ChatDev 2.0**：候选可视化工作流和中间产物体验参考；
4. **MetaGPT**：岗位、SOP 和结构化阶段产物参考；
5. **CAMEL + MiroFish/OASIS**：Agent 社会、对抗和大规模仿真参考。

## 2. 评价维度

本轮不只看“能不能运行多个 Agent”，而是按以下维度评价：

- 是否有确定性工作流、DAG、并行、条件、循环和汇合；
- Agent 是否具有独立角色、知识、工具、记忆和权限；
- 是否支持协作、委托、Handoff、评审、辩论或红蓝对抗；
- 是否有中间产物，而不是只保存聊天消息；
- 是否支持暂停、恢复、检查点、人工输入和长任务；
- 是否有事件、Trace、成本和运行可视化；
- 是否支持知识检索、证据引用和长期记忆；
- 是否有评测、基准和单/多 Agent 对比能力；
- 是否容易与现有 Python、FastAPI、PostgreSQL 架构隔离集成；
- 项目活跃度、许可证和产品方向是否适合作为长期依赖。

## 3. 第一梯队：最值得作为底层或关键模块候选

### 3.1 Microsoft Agent Framework

- 仓库：[microsoft/agent-framework](https://github.com/microsoft/agent-framework)
- 语言：Python、.NET
- 许可证：MIT
- 社区规模：约 1.2 万 Stars
- 定位：微软面向生产环境的 Agent 与多 Agent 工作流框架，是 AutoGen 和 Semantic Kernel Agent 能力的新主路线。

核心能力：

- 图式工作流；
- Sequential、Concurrent、Handoff、Group Collaboration；
- Checkpoint、Streaming、Human-in-the-loop 和 Time-travel；
- 多模型供应商；
- Middleware；
- OpenTelemetry 可观察性；
- YAML 声明式 Agent；
- A2A、Durable Agents、Durable Workflows 和托管样例；
- Python 与 .NET 双语言支持；
- DevUI 开发调试界面。

与本项目相似之处：

- “确定性图骨架 + 多 Agent 节点”的方向高度一致；
- 检查点、重启恢复、HITL、流式事件和可观察性正是 PRD P0 所需；
- Handoff 和协作模式可以映射为平台的 Coordination Strategy。

缺口：

- 没有江湖 Online 的 Artifact/Evidence/Defect/Revision/Decision 领域闭环；
- 自动从需求生成生产流程不是它的完整产品能力；
- Agent 社会关系、独立裁判和多 Agent 价值实验仍需自建；
- 官方生态与 Azure/Foundry 联系较深，需验证完全本地和非 Azure 模型路径。

判断：**首选底层 POC 候选之一**。应通过 Adapter 使用，不能让其 Workflow 对象直接成为平台公开模型。

### 3.2 LangGraph

- 仓库：[langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)
- 语言：Python，另有 JavaScript 版本
- 许可证：MIT
- 社区规模：约 3.8 万 Stars
- 定位：构建长时间、持久化、有状态 Agent 的低层编排框架。

核心能力：

- StateGraph、Node、Edge、Subgraph；
- Durable Execution 和 Checkpoint；
- Interrupt/Human-in-the-loop；
- 短期与长期记忆；
- 分支、并行、循环和状态归并；
- 多 Agent Supervisor、Handoff、Subagent 和 Router 模式；
- 流式事件；
- 可独立使用，也可配合 LangSmith Studio、Trace 和评测。

与本项目相似之处：

- 适合实现 PRD 中的可恢复 DAG 和人工介入；
- 显式 State 和上下文输入输出适合实现 Artifact 引用与最小上下文策略；
- 子图可封装“有限辩论”“红队审查”等复合节点。

缺口：

- 正式产物、证据和缺陷仍需要平台自己的数据模型；
- LangSmith 的部分可视化、部署和评测属于商业生态，不应成为 MVP 必需依赖；
- 框架自由度高，需要团队自行规定事件、幂等、版本和安全边界。

判断：**当前 Python 技术栈下最现实的图执行 POC 候选**。

### 3.3 AgentScope 2.0

- 仓库：[agentscope-ai/agentscope](https://github.com/agentscope-ai/agentscope)
- 语言：Python
- 许可证：Apache-2.0
- 社区规模：约 2.8 万 Stars
- 定位：可观察、可理解、可信任的生产级 Agent 框架与服务。

核心能力：

- 统一消息和事件系统，可连接前端并支持 HITL；
- 工具和资源细粒度权限系统；
- 多租户、多会话 Agent Service；
- Agent Team，Leader 动态派生和管理 Worker；
- 任务规划与后台任务；
- Local、Docker、E2B、OpenSandbox、Daytona、Kubernetes 等工作区/沙箱；
- RAG、长期记忆和中间件；
- FastAPI 服务和示例 Web UI；
- 流式事件输出。

与本项目相似之处：

- 技术栈与当前 FastAPI/Python 方向接近；
- 权限、沙箱、多会话、事件、Agent Team 和后台任务具有很强的直接借鉴价值；
- 可以作为 `AgentExecutionPort` 的执行端，而由江湖 Online 继续控制正式工作流。

缺口：

- 重点仍是 Agent 服务和团队，不是正式 Artifact 生产流；
- 对抗、裁判、缺陷修订和版本追溯需自建；
- 2.0 较新，接口稳定性和迁移成本需验证。

判断：**最值得验证的 Agent Worker/沙箱/权限候选**，不一定替代领域 Orchestrator。

### 3.4 CrewAI

- 仓库：[crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)
- 语言：Python
- 许可证：MIT
- 社区规模：约 5.6 万 Stars
- 定位：通过 Crew 提供角色化自治协作，通过 Flow 提供精确的事件驱动流程。

核心能力：

- Agent、Role、Goal、Task、Tool 和 Crew；
- 顺序与层级式团队协作；
- Flow 状态和事件驱动控制；
- Flow 中调用 Crew，也可混合普通 Python、单次 LLM 调用和多 Agent 团队；
- 结构化输出、Guardrail、Memory、Knowledge、HITL；
- Trace、部署和控制平面的商业产品。

与本项目相似之处：

- “Flow 管确定性主流程，Crew 负责局部自治团队”与推荐架构很接近；
- Role/Goal/Task 易于快速验证 Agent Blueprint 和团队模板；
- 适合快速做委托、并行专家和评审原型。

缺口：

- 正式产物和证据闭环仍需平台自建；
- 开源框架与商业控制平面的边界需要核对；
- 对复杂 DAG、持久恢复、精确取消和框架内部状态映射需实测；
- 高层抽象虽然开发快，但可能限制本项目独特的对抗协议。

判断：**快速业务 POC 很合适，长期内核需谨慎评估**。

## 4. 第二梯队：与产品形态和用户体验高度相似

### 4.1 ChatDev 2.0 / DevAll

- 仓库：[OpenBMB/ChatDev](https://github.com/OpenBMB/ChatDev)
- 语言：Python + Web
- 许可证：Apache-2.0
- 社区规模：约 3.4 万 Stars
- 定位：由“虚拟软件公司”演化为零代码通用多 Agent 编排平台。

ChatDev 2.0 的重要变化：

- 用户可以零代码定义 Agent、Workflow 和 Task；
- 提供拖拽式 Workflow Canvas；
- 配置节点参数与 Context Flow；
- 运行时展示实时日志、中间 Artifact 和 HITL 反馈；
- YAML 工作流可校验、同步并通过 Python SDK 执行；
- FastAPI 后端，独立 Runtime、Workflow 和 Tool 模块；
- 提供 Deep Research、视频、数据分析及多 Agent 仿真模板；
- 可由 OpenClaw 调用现有团队或动态创建 ChatDev 团队。

ChatDev 1.0 则以软件公司为隐喻，由 CEO、CTO、产品、程序员、测试等角色按 ChatChain/Phase 生产软件，支持 Human Reviewer、日志和回放。

与本项目相似之处：

- 自然语言/配置驱动生成和运行多 Agent 流程；
- 可视化画布、运行日志、中间产物和人工反馈；
- 角色团队与生产阶段都很接近江湖 Online 的表现形态；
- MacNet 使用 DAG 组织语言交互，Puppeteer 路线研究动态激活和排序 Agent。

缺口：

- 需要核查 Artifact 是否具备不可变版本、来源、证据和下游精确引用；
- 对抗缺陷、修订、复测和正式裁判不是完整的一等对象；
- 自动生成工作流的可解释性、静态校验和安全治理仍需深入看代码；
- 2.0 发布较新，架构稳定性和文档完整度需实测。

判断：**当前产品形态最相似的开源项目之一，应作为重点拆解对象**。可重点研究其 YAML Schema、前端画布、Runtime、Artifact 和 HITL 实现。

### 4.2 MetaGPT

- 仓库：[FoundationAgents/MetaGPT](https://github.com/FoundationAgents/MetaGPT)
- 语言：Python
- 许可证：MIT
- 社区规模：约 7 万 Stars
- 定位：将软件公司的岗位、标准作业程序和阶段产物映射为多 Agent 系统。

核心理念：

> `Code = SOP(Team)`：把 SOP 物化，并应用到由产品经理、架构师、项目经理、工程师等组成的团队。

典型流程：

```text
一句需求
-> 产品需求/用户故事
-> 系统设计
-> 任务分解
-> 代码
-> 测试与修订
```

核心能力：

- Role、Action、Message、Environment 和 Team；
- Agent 订阅相关消息，按 SOP 执行动作；
- 不同岗位生成不同阶段的文档和代码；
- 支持 Debate、Researcher、Data Interpreter 等用例；
- AFlow 研究自动生成和优化 Agentic Workflow；
- MGX 延续 AI 软件开发团队的产品化方向。

与本项目相似之处：

- 最接近“真实生产岗位 + 标准流程 + 阶段交付物”的概念；
- 证明多 Agent 不必围绕聊天，而可围绕 SOP 和产物协作；
- Product Manager、Architect、Reviewer 等角色和本项目首个案例高度贴合。

缺口：

- 默认以软件研发场景为中心，不是自动适配任意生产流；
- 产物版本、证据、缺陷和裁判治理仍不够通用；
- 自由消息订阅机制不等同于严格可恢复的业务 DAG；
- UI、HITL、运行控制和企业权限不是开源核心的最大优势。

判断：**重点借鉴 SOP、角色职责、阶段 Artifact 和需求到开发方案案例，不建议直接作为平台内核**。

### 4.3 AutoGen 与 AutoGen Studio

- 仓库：[microsoft/autogen](https://github.com/microsoft/autogen)
- 语言：Python、.NET
- 当前状态：官方标记为 maintenance mode
- 定位：多 Agent 对话、消息事件运行时与 Studio 原型工具。

历史核心能力：

- AssistantAgent、AgentTool 和多种 Team；
- RoundRobin、Selector、Swarm、GraphFlow 等模式；
- Event-driven Core 和分布式 Runtime；
- AutoGen Studio 无代码原型；
- AutoGen Bench 评测；
- Magentic-One 通用多 Agent 团队。

判断变化：

- 其团队模式、GraphFlow、事件和 Studio 仍值得研究；
- 但官方已经建议新项目使用 Microsoft Agent Framework；
- 不应再作为本项目新的长期依赖进入主路径。

判断：**保留为模式和历史案例参考，不作为新底座首选**。

## 5. 第三梯队：Agent 社会、对抗和大规模模拟参考

### 5.1 CAMEL

- 仓库：[camel-ai/camel](https://github.com/camel-ai/camel)
- 语言：Python
- 许可证：Apache-2.0
- 社区规模：约 1.7 万 Stars
- 定位：研究 Agent 社会、角色扮演、协作、记忆、环境和规模规律的通用框架。

核心能力：

- ChatAgent、RolePlaying、Workforce 和 Agent Society；
- Critic Agent、Tree Search、Judge Committee；
- Memory、Storage、RAG、GraphRAG、Tools 和 HITL；
- Benchmark 和结构化数据生成；
- 大规模 Agent 协调和社会环境；
- OASIS、MiroFish 等项目的重要底层来源。

与本项目相似之处：

- 可建立不同身份、立场、知识和关系的 Agent 社会；
- Critic/Judge/Committee 适合对抗和裁判模式；
- Workforce 可参考动态团队组建和任务分工；
- GraphRAG 与动态知识图谱适合江湖视图和证据网络。

缺口：

- 更偏研究积木，平台级工作流、Artifact 版本和治理需要自行完成；
- 大规模 Agent 不自动带来生产质量，成本与收敛需要严格限制。

判断：**社会体系、对抗协议和研究实验的重要参考，可在局部节点做适配 POC**。

### 5.2 MiroFish

- 仓库：[666ghj/MiroFish](https://github.com/666ghj/MiroFish)
- 语言：Python + Vue
- 许可证：AGPL-3.0
- 定位：从用户材料构建知识图谱和人格，运行社交媒体式 Agent 社会模拟，再生成分析报告。

核心流程：

```text
资料与推演目标
-> Ontology/知识图谱
-> 实体转 Agent Persona
-> 生成模拟参数
-> OASIS 社会环境互动
-> 行为与记忆回写
-> ReportAgent 检索、采访和生成报告
```

与本项目相似之处：

- 从知识和目标自动生成 Agent；
- 可观察多个 Agent 的讨论、立场、关系和影响；
- Agent 行为写回长期记忆；
- ReportAgent 可检索证据并采访 Agent；
- Vue + Python 的产品形态与当前项目接近。

缺口：

- 是社会仿真，不是正式生产工作流；
- 缺少任务依赖、阶段 Artifact、质量门、返工和强状态机；
- 社交媒体环境对业务生产流程不通用；
- AGPL-3.0 和 Zep Cloud 依赖需要重点评估。

判断：**“江湖视图”、动态人格、关系、群体互动、报告与采访的最佳参考之一，但不适合直接作为生产流内核**。

### 5.3 OASIS

- 仓库：[camel-ai/oasis](https://github.com/camel-ai/oasis)
- 语言：Python
- 许可证：Apache-2.0
- 社区规模：约 5000 Stars
- 定位：可扩展到大量 Agent 的开放社会互动模拟框架。

核心能力：

- Twitter/Reddit 等社会环境；
- Agent Graph、Profile、Environment、Action 和时间步；
- 不同模型、工具和 Prompt；
- 人工 Action 与 Agent 采访；
- 行为数据存储、可视化和分析；
- 面向百、千、万乃至更大规模 Agent 的实验。

判断：**适合未来“大江湖”和群体涌现实验，不适合 MVP 正式生产流程**。

### 5.4 AgentVerse

- 仓库：[OpenBMB/AgentVerse](https://github.com/OpenBMB/AgentVerse)
- 语言：Python/JavaScript
- 许可证：Apache-2.0
- 社区规模：约 5000 Stars
- 定位：同时支持 Task-solving 和 Simulation 的早期多 Agent 框架。

核心能力：

- 多 Agent 协作解决任务；
- 自定义环境和社会模拟；
- NLP Classroom、Prisoner's Dilemma、软件设计等案例；
- ChatEval 使用多角色裁判团队辩论并评价文本；
- 支持基准任务和部分工具调用。

风险：

- 主仓库最近公开活跃度较低；
- README 明确存在重构状态，部分稳定功能需使用旧分支；
- 生产恢复、权限和平台治理能力较弱。

判断：**适合研究多角色辩论、囚徒困境和 ChatEval，不适合作为生产底座**。

## 6. 其他值得观察但相似度较低的项目

### 6.1 OpenManus

- 仓库：[FoundationAgents/OpenManus](https://github.com/FoundationAgents/OpenManus)
- 许可证：MIT
- 社区规模：约 5.8 万 Stars

它主要是通用 Agent/Manus 类任务执行框架，包含规划、工具和浏览器能力，也有一个仍被官方称为“不稳定”的多 Agent Flow。它适合参考通用执行 Agent、工具使用和规划，但与“生产流程生成 + 对抗 + Artifact 治理”的差距较大。

### 6.2 OpenClaw

- 仓库：[openclaw/openclaw](https://github.com/openclaw/openclaw)
- 许可证：MIT

它适合参考或承担长期 Agent、子 Agent 派生、工具权限、沙箱和多渠道入口，但不提供江湖 Online 所需的完整正式产物生产流。详细分析见 `openclaw-and-multi-agent-technical-options.md`。

## 7. 横向评分

评分说明：5 表示开源核心中能力较强，1 表示基本缺失。评分是面向江湖 Online 需求的工程判断，不是通用项目排名。

| 项目 | 确定性流程 | 多 Agent 协作 | 对抗/裁判 | 中间产物 | 恢复/HITL | 权限/沙箱 | 可视化 | 社会模拟 | 作为底座适合度 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Microsoft Agent Framework | 5 | 5 | 3 | 2 | 5 | 3 | 3 | 1 | 5 |
| LangGraph | 5 | 4 | 3 | 2 | 5 | 2 | 3 | 1 | 5 |
| AgentScope | 3 | 4 | 2 | 2 | 4 | 5 | 3 | 2 | 4 |
| CrewAI | 4 | 5 | 3 | 3 | 3 | 3 | 2 | 2 | 4 |
| ChatDev 2.0 | 4 | 5 | 3 | 4 | 3 | 2 | 5 | 3 | 4 |
| MetaGPT | 3 | 5 | 3 | 5 | 2 | 2 | 2 | 1 | 3 |
| AutoGen | 4 | 5 | 4 | 2 | 4 | 2 | 4 | 3 | 2 |
| CAMEL | 2 | 5 | 5 | 2 | 3 | 2 | 2 | 5 | 3 |
| MiroFish | 2 | 4 | 3 | 3 | 2 | 2 | 4 | 5 | 2 |
| OASIS | 1 | 4 | 4 | 1 | 2 | 2 | 3 | 5 | 1 |
| AgentVerse | 2 | 4 | 5 | 2 | 2 | 1 | 3 | 5 | 1 |

## 8. 推荐拆解顺序

### 第一轮：直接关系到技术底座

1. Microsoft Agent Framework：工作流、Checkpoint、HITL、Time-travel 和事件。
2. LangGraph：StateGraph、持久化、Interrupt、Subgraph、并行和状态归并。
3. AgentScope：Agent Service、事件、权限、沙箱和 Agent Team。

输出：统一 POC、性能和恢复对比、是否采用框架的 ADR。

### 第二轮：直接关系到产品体验

1. ChatDev 2.0：YAML Workflow、画布、运行页、Artifact 和 HITL。
2. MetaGPT：SOP、Role/Action/Message、阶段文档和软件团队案例。

输出：Workflow Definition Schema、Agent Blueprint Schema、Artifact 生命周期和界面参考。

### 第三轮：差异化能力

1. CAMEL：Workforce、Critic、Judge Committee 和 Agent Society。
2. MiroFish：知识图谱生成 Persona、关系视图、采访和报告。
3. OASIS：环境、动作、Agent Graph 和大规模模拟。
4. AgentVerse/ChatEval：多角色裁判和辩论评测。

输出：Society Template、Debate Protocol、Evaluation Suite 和“大江湖”演进路线。

## 9. 建议复用与自研边界

| 能力 | 建议 |
| --- | --- |
| 图调度、检查点、Interrupt | 优先验证 MAF/LangGraph，避免从零实现所有机制 |
| Agent Worker、沙箱和权限 | 深入验证 AgentScope，也可参考 OpenClaw |
| 可视化画布和 YAML 工作流 | 参考 ChatDev 2.0，平台自行定义 Schema |
| SOP、岗位和阶段产物 | 参考 MetaGPT，自建通用领域模型 |
| 辩论、Critic、委员会 | 参考 CAMEL、AutoGen、ChatEval，自建有限轮次协议 |
| 社会关系、人格和涌现 | 参考 MiroFish/OASIS，作为 P1/P2 能力 |
| Artifact/Evidence/Defect/Revision/Decision | 必须由江湖 Online 自研并作为唯一真相源 |
| 版本、幂等、预算、安全审批和评测 | 必须由平台统一治理，不交给单个框架 |

## 10. 下一步建议

不建议继续只做文档层面的横向比较。下一步应选择四个项目做同题 POC：

```text
共同输入：一份产品需求和知识资料
共同任务：输出技术方案，进行红队审查，完成修订和裁决

A. LangGraph
B. Microsoft Agent Framework
C. AgentScope + 自研轻量 DAG
D. ChatDev 2.0
```

统一记录：

- 实现工作量和代码侵入度；
- DAG、并行、循环、汇合和人工节点能力；
- 重启恢复、取消、超时、重试和幂等；
- 结构化 Artifact 成功率；
- 事件与 UI 接入难度；
- 工具、知识和沙箱权限；
- Token、时延和并发；
- 框架升级、许可证和部署成本。

POC 结果再决定是否采用底层框架；无论选哪个，江湖 Online 的领域对象和公开 API 都应保持框架无关。

## 11. 第二轮补充：低热度但概念高度一致的项目

本节刻意降低 Stars 权重。部分项目规模较小、处于研究或快速开发阶段，不建议未经验证直接成为依赖，但其概念设计对江湖 Online 很有价值。

### 11.1 EvoAgentX：从目标自动生成并持续演化工作流

- 仓库：[EvoAgentX/EvoAgentX](https://github.com/EvoAgentX/EvoAgentX)
- 许可证：MIT
- 调研时社区规模：约 3000 Stars
- 定位：自动构建、评价和演化 Agent/多 Agent Workflow。

核心能力：

- 用户只提供目标，由 `WorkFlowGenerator` 生成结构化多 Agent 工作流；
- `WorkFlowGraph` 可视化、保存和重新加载；
- `AgentManager` 根据工作流实例化 Agent；
- 内置任务评价器；
- 使用反馈循环和多种演化算法优化工作流；
- 支持短期、长期记忆；
- 支持 HITL 检查点；
- 内置检索、文件、浏览器、数据库、Python 和 Docker 隔离工具。

与本项目高度相似的部分：

```text
自然语言目标
-> 自动生成 Agent 团队与工作流
-> 执行
-> 按任务指标评价
-> 优化工作流
```

这与 PRD 的“用户表达需求后自动生成流程和 Agent，并通过评测持续改进”非常接近。

主要缺口：

- 生成的是 Agentic Workflow，未原生覆盖 Artifact/Evidence/Defect/Decision；
- 进化依赖数据集和评价函数，不能直接把裁判模型分数视为真实质量；
- 生产级恢复、幂等、权限和多用户治理仍需深入验证。

判断：**新增为第一优先级研究对象**。建议重点拆解其 Workflow Graph Schema、生成 Prompt、Evaluator 和 Evolution 接口。

### 11.2 AFlow：用搜索自动发现高性能 Agent 工作流

- 仓库：[FoundationAgents/AFlow](https://github.com/FoundationAgents/AFlow)
- 社区规模：约 500 Stars
- 背景：ICLR 2025 Oral，MetaGPT 团队的自动工作流生成研究。

核心思想：

- 将 Agent Workflow 表示为代码或图；
- 使用 LLM 和蒙特卡洛树搜索探索工作流空间；
- 对候选工作流执行、评分和反馈；
- 逐轮选择、扩展、评估和更新，寻找比人工设计更有效的工作流；
- 支持接入自定义 Dataset、Benchmark 和 Evaluation Function。

对本项目的意义：

- 证明“流程不是固定模板，也可以被生成和优化”；
- 可以用于后期优化节点顺序、Agent 数量、辩论轮次和模型选择；
- 很适合作为 Evaluation Lab 的离线实验能力。

限制：

- 目前更偏基准研究工具，而非在线生产运行时；
- 搜索成本较高；
- 优化目标容易导致过拟合；
- 不应让在线用户任务直接执行未经审核的自动生成代码。

判断：**适合 P2 的流程优化实验，不适合作为 MVP 主运行时**。

### 11.3 GEAR：框架无关的多 Agent 设计与代码生成层

- 仓库：[brellsanwouo/gear-framework](https://github.com/brellsanwouo/gear-framework)
- 调研时社区规模：约 70 Stars
- 定位：设计一次多 Agent 系统，再生成多个运行框架的实现。

核心能力：

- 使用 YAML 描述 Agent、Task、Module、工具、记忆、模型和工作流；
- 支持顺序、并行、循环、分支和汇合；
- 构建前进行阻断式静态校验；
- 提供 Guided Studio 和图形化编排；
- 可生成 LangGraph、Microsoft Agent Framework、OpenAI Agents SDK、Google ADK、CrewAI、AutoGen、Strands、PydanticAI、Semantic Kernel、Haystack 等目标代码；
- 生成的 Python Artifact 可以独立运行；
- 对生成代码执行增加 CPU、内存、文件、描述符和时间限制。

与推荐架构的关系：

GEAR 的“框架无关声明层 → Adapter/代码生成 → 多运行时”与前一份技术方案中提出的 `AgentExecutionPort` 思想非常接近。

值得借鉴：

- 平台领域 Schema 与底层框架解耦；
- 发布前静态校验；
- 同一设计生成多种运行实现；
- 生成 Artifact 可检查、测试和版本化，而不是黑箱执行。

风险：

- 项目较新且社区较小；
- 同时兼容大量框架会产生最低公共能力集和维护成本；
- 代码生成后的升级、回迁和语义一致性需要验证。

判断：**概念非常值得借鉴，代码是否复用取决于 POC**。

### 11.4 GPTSwarm：把 Agent 团队建模为可优化图

- 仓库：[metauto-ai/GPTSwarm](https://github.com/metauto-ai/GPTSwarm)
- 调研时社区规模：约 1000 Stars
- 定位：将 Agent 和 Agent 间连接表示为图，并优化群体拓扑。

核心能力：

- Agent、Tool、Task 和 Operation 构成节点；
- Agent Swarm 是可执行图；
- 可视化 Agent 图；
- 优化 Agent 之间边的概率；
- 自动剪除低价值连接、保留有效协作路径；
- 支持本地模型和基准任务。

对本项目的意义：

- “Agent 数量和连接关系可优化”比固定组织结构更接近长期的学习型江湖；
- 可用于比较星型、层级、流水线、全连接和稀疏拓扑；
- 可将质量、费用和时延共同纳入拓扑优化目标。

限制：

- 研究重点是性能优化，不是生产 Artifact 和治理；
- 优化出的图未必符合职责分离、安全和组织制度；
- 自动优化必须受 Policy 和权限约束。

判断：**适合 Evaluation Lab 和 P2 组织优化研究**。

### 11.5 AgentPrune：剪除冗余或恶意的 Agent 通信

- 仓库：[yanweiyue/AgentPrune](https://github.com/yanweiyue/AgentPrune)
- 调研时社区规模：约 100 Stars
- 背景：ICLR 2025
- 定位：优化多 Agent 的空间与时间通信拓扑。

核心能力：

- 剪除冗余消息和低价值 Agent 连接；
- 同时优化“谁与谁通信”和“在哪一轮通信”；
- 对恶意或错误 Agent 消息具有一定鲁棒性；
- 提供 MMLU、HumanEval、GSM8K 实验；
- 展示与 AutoGen RoundRobin 和 GPTSwarm 的逻辑集成。

对本项目的启示：

- Live Arena 不应默认让所有 Agent 看到所有消息；
- Context Policy 可以基于相关性、角色、证据和历史贡献选择通信；
- 多 Agent 价值指标应包含“通信有效率”和“无效讨论成本”；
- 对抗 Agent 的错误信息不能无条件传播到正式产物。

判断：**不作为运行底座，但值得转化为上下文路由和成本治理需求**。

### 11.6 GAIA Blackboard：通过共享 Artifact/Evidence 黑板协作

- 仓库：[GAIA Environment-Mediated Coordination](https://github.com/MEHUL-MODI-Git/GAIA-Environment-Mediated-Coordination-for-Multi-Agent-LLM-Collaboration)
- 社区规模很小
- 许可证状态：README 明确说明当前未授予开源许可证，只能研究和参考，不能直接复用代码。

核心能力：

- 不依赖多个 Agent 不断群聊，而是通过 Shared Blackboard 协作；
- 黑板包含 Task、Artifact、Evidence 和 Signal；
- Agent 可自助领取带租约的任务；
- 根据积压动态派生 Agent；
- 将冲突转化为新的待解决任务；
- 提供单 Agent、多 Agent 对话和完整黑板协作的实验对比；
- 包含独立验证和基准实验。

这是本轮概念上与江湖 Online 最接近的发现之一：

```text
共享聊天历史                  共享生产黑板
    ↓                             ↓
容易信息污染          Task / Artifact / Evidence / Signal
    ↓                             ↓
依赖模型自行协调          任务领取、租约、冲突升级、验证
```

可直接吸收的设计思想：

- Shared Memory 不应只是消息列表，而应是结构化业务黑板；
- Agent 通过 Artifact 和 Evidence 协作；
- 冲突不是继续自由争论，而是转成明确的验证任务；
- Task Claim 需要租约、超时和重新分配；
- 快慢模型可对应不同风险和任务类型。

判断：**概念重点吸收，代码不可复用**。

### 11.7 Consensus Pipeline：需求访谈—多部门辩论—逐主张置信度

- 仓库：[fangqian616/consensus-pipeline](https://github.com/fangqian616/consensus-pipeline)
- 社区规模很小
- 定位：面向学术研究的结构化多 Agent 辩论和报告生产流水线。

核心流程：

```text
需求访谈
-> 自动生成十余个专业部门和辩手
-> 文献搜索与三层质量过滤
-> 每个部门多轮辩论
-> 跨部门交叉验证
-> 结构化共识 JSON
-> 带逐主张置信度与引用的报告
-> PDF/DOCX、代码与辩论日志
```

与本项目相似之处：

- 先访谈澄清目标和约束；
- 根据任务动态生成专业角色/部门；
- 对每个结论进行独立挑战；
- 不是只输出最终答案，还输出辩论日志、结构化共识和置信度；
- Streamlit 页面实时展示辩论；
- 最终结果包含引用、置信度和可下载 Artifact。

缺口：

- 场景固定在文献综述；
- 目前跨部门配对和评价指标仍较粗；
- 置信度多为流程内部统计，不能直接等同于事实概率；
- 完整权限、恢复和版本治理不足。

判断：**非常适合参考有限辩论节点、动态团队生成、逐主张证据和置信度展示**。

### 11.8 Internet of Agents：异构 Agent 自主组队

- 仓库：[OpenBMB/IoA](https://github.com/OpenBMB/IoA)
- 定位：让来自不同框架、环境和设备的 Agent 像互联网节点一样协作。

核心能力：

- 连接 AutoGPT、Open Interpreter、ReAct Agent 等异构 Agent；
- Agent 自主形成团队和子团队；
- 异步任务执行；
- 自适应会话流；
- Agent 通过容器化 Client/Server 架构连接；
- 支持任务明确指定成员，也支持动态组队。

对本项目的意义：

- 适合参考未来外部 Agent Registry 和跨框架团队；
- Agent 能力描述、发现、组队和任务协商可与 A2A 演进结合；
- 证明平台不应假定所有 Agent 都由同一套 SDK 实现。

限制：

- 更偏研究型互联和对话协作；
- 正式产物、权限、证据和质量门需要平台补充；
- 部署组件较多，MVP 不宜优先接入。

判断：**P1/P2 外部 Agent 生态参考**。

### 11.9 PraisonAI：轻量工作流、策略和可视化入口

- 仓库：[MervinPraison/PraisonAI](https://github.com/MervinPraison/PraisonAI)
- 定位：用较低代码量构建单 Agent、多 Agent 和 AI Workforce。

核心能力：

- 顺序、路由、并行、循环、条件、分支和 Early Stop；
- Evaluator-Optimizer/Repeat 模式；
- Agent Handoff、自反思和自动 Agent；
- Workflow Checkpoint；
- Background Task 和死循环检测；
- Policy Engine；
- A2A、MCP、Graph Memory；
- YAML 无代码定义；
- 可连接 Langflow 进行可视化编排；
- 可调度 Claude Code、Codex、Gemini CLI 等外部执行 Agent。

与本项目相似之处：

- 能力覆盖面与 PRD 的节点类型很接近；
- Evaluator-Optimizer 可快速模拟提案—审查—修订；
- 外部 Agent 调度和 Policy Engine 值得研究。

风险：

- 功能面很广，需要核查每项能力的实现深度、测试和兼容性；
- Dashboard/Flow 中部分能力由其他组件提供；
- 正式 Artifact/Evidence 治理仍不完整。

判断：**适合进入轻量 POC 对照组**。

### 11.10 AgenticX：国内社区的全栈多 Agent 平台尝试

- 仓库：[DemonDamon/AgenticX](https://github.com/DemonDamon/AgenticX)
- 调研时社区规模：约 200 Stars
- 定位：SDK、CLI、Studio、桌面端和平台服务一体的多 Agent 框架。

其公开架构包含：

- Meta-Agent/CEO 调度和 Team Manager；
- 图工作流、Flow、条件路由和并行；
- 类型化事件流和 ReAct 执行器；
- 分层记忆、GraphRAG 和知识库；
- A2A、MCP；
- Agent 自修复、卡死检测和长任务恢复；
- FastAPI Studio、WebSocket、Electron 桌面端；
- 多租户会话隔离；
- EvalSet、LLM Judge、组合裁判和轨迹匹配；
- PostgreSQL、Redis、MongoDB、Neo4j 等存储适配。

与本项目相似之处：

- 产品层次完整，覆盖 Studio、Runtime、Memory、Protocol、Security、Evaluation；
- CEO 派生团队、工作流、评价和长任务与江湖 Online 很接近；
- Python/FastAPI 技术路线相似。

风险：

- 能力声明很多，必须通过源码、测试和实际运行验证成熟度；
- 项目快速变化，模块边界和兼容性可能不稳定；
- 不应因为功能列表相似就直接采用整套框架。

判断：**值得做代码结构和产品分层研究，但底座选型必须实测**。

### 11.11 Swarms：大量预制组织拓扑

- 仓库：[kyegomez/swarms](https://github.com/kyegomez/swarms)
- 定位：提供大量可直接使用的多 Agent 组织和编排结构。

代表模式：

- SequentialWorkflow；
- ConcurrentWorkflow；
- GraphWorkflow；
- AgentRearrange；
- Mixture of Agents；
- GroupChat；
- ForestSwarm；
- HierarchicalSwarm；
- HeavySwarm；
- SwarmRouter。

对本项目最有价值的是“组织拓扑模式库”：

- `AgentRearrange` 用简洁语法定义一对多、多对一和混合关系；
- `HeavySwarm` 固定包含研究、分析、替代方案和验证等阶段；
- `Mixture of Agents` 可实现并行专家加汇总；
- `HierarchicalSwarm` 对应管理者分解和分派任务。

限制：

- 项目提供大量抽象，需要逐个验证持久化、恢复和治理深度；
- 其“Swarm”更多是模式集合，不代表都适合正式生产；
- 本项目应吸收模式定义，不应原样把 60 多种结构暴露给普通用户。

判断：**适合形成 Coordination Strategy 模式库参考**。

## 12. 补充项目优先级

| 优先级 | 项目 | 重点研究问题 |
| --- | --- | --- |
| S | EvoAgentX | 如何从一句目标生成 Agent 和 Workflow，如何评价和演化 |
| S | GAIA Blackboard | 如何通过 Task/Artifact/Evidence/Signal 黑板替代群聊 |
| S | GEAR | 如何保持平台 Schema 与底层框架无关并生成可运行 Artifact |
| A | Consensus Pipeline | 如何实现访谈、动态团队、有限辩论、逐主张证据与置信度 |
| A | AFlow | 如何用数据集和评测函数自动搜索更优工作流 |
| A | GPTSwarm/AgentPrune | 如何优化团队拓扑、上下文路由和通信成本 |
| A | PraisonAI | 轻量工作流、Evaluator-Optimizer、Policy 和外部 Agent |
| B | AgenticX | 全栈平台分层、事件、长任务、自修复和评价体系 |
| B | IoA | 异构外部 Agent 的发现、组队和协作 |
| B | Swarms | 多 Agent 组织与编排模式库 |

## 13. 补充结论

第二轮调研进一步说明，江湖 Online 的差异化不应建立在“我们支持更多 Agent 框架”上，而应建立在以下统一能力上：

1. **需求编译器**：参考 EvoAgentX，从目标、知识、约束和验收标准生成流程和团队草案。
2. **生产黑板**：参考 GAIA，将 Task、Artifact、Evidence、Defect、Decision 和 Signal 作为协作对象。
3. **框架无关执行**：参考 GEAR，用稳定 Schema 和 Adapter 面向多个运行时。
4. **有限对抗协议**：参考 Consensus Pipeline、CAMEL 和 ChatEval，把争论转化为证据、缺陷和裁决。
5. **组织与通信优化**：参考 GPTSwarm 和 AgentPrune，测量并削减无效 Agent、边和消息。
6. **评测驱动演进**：参考 AFlow，以数据集、规则和人工评分优化流程，但不让在线流程未经审批自行变异。

从概念匹配度看，下一轮最值得直接拉代码做架构拆解的是：**EvoAgentX、GEAR、GAIA Blackboard、Consensus Pipeline**。
