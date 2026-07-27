# 企业级 Agent 平台与社会模拟补充调研

> 日期：2026-07-24  
> 目的：在编排框架调研基础上，补充企业 Agent 平台、Agent 资产治理、评测、协议互操作、安全和社会模拟能力。  
> 证据原则：产品事实优先采用官方文档；GitHub 项目以官方仓库 README 和代码为依据。

## 1. 本轮新增研究问题

1. 企业如何管理不断增加的 Agent、工具和工作流？
2. 不同团队创建的 Agent 如何发现、复用和协作？
3. Agent 如何测试、发布、监控、审计和持续改进？
4. 社会模拟框架中的人格、关系、环境和记忆，哪些适用于生产工作流？
5. Agent Arena 如何避免成为另一个普通工作流画布？

## 2. 企业平台实践

### 2.1 Microsoft Copilot Studio

Copilot Studio 的 Connected Agents 采用“主 Agent + 独立专业 Agent”：

- 专业 Agent 拥有独立的指令、知识、工具和编排上下文。
- 主 Agent 根据描述选择专业 Agent，并传递相关对话内容。
- 专业 Agent 可被多个主 Agent 复用，并由不同团队维护。
- Agent 之间可以显式重定向，也可以由生成式编排自动选择。
- 官方同时提醒，多 Agent 会增加延迟、测试面和治理成本。

新增的平台能力还包括 Agent Inventory、组织数据连接、多轮测试、组件集合、人工输入和运行 Activity Map。

**启示：**

- Agent 应是独立、可发布、可授权、可复用的组织资产。
- Agent 描述不仅用于展示，也是运行时路由依据，需要可测试。
- 平台必须展示多次编排跳转带来的成本和延迟。
- 父 Agent 不应默认获得子 Agent 的全部内部上下文。

### 2.2 IBM watsonx Orchestrate

IBM 将产品定位为企业 Agent 的集中编排与控制平面，重点包括：

- 在 ReAct、Plan-Act 和确定性编排之间选择。
- 主 Agent、协作 Agent、Handoff 条件及输入输出映射。
- 内部 Agent、目录 Agent、第三方 Agent 和 A2A Agent 的统一接入。
- 受治理的 Agent、工具和模板目录。
- 多模型路由、实时监控、策略与审计。
- Agentic Control Plane 管理整个 Agent 生态。

IBM 的普通协作 Agent 默认顺序执行；需要并行时进入 Agentic Workflow。这再次说明“自治协作”和“确定性流程”需要两种执行语义。

**启示：**

- Agent Arena 需要统一资产目录和控制平面。
- Handoff 条件、输入映射和输出 Artifact 应显式配置。
- 外部 Agent 不能直接混入内部运行时，应经过注册、能力发现、身份和策略校验。

### 2.3 Google Vertex AI 与 Agent Registry

Vertex AI Agent Engine 将生产能力拆成：

- 托管运行时与弹性扩缩。
- Session、记忆和上下文管理。
- 评估、示例库和优化。
- 基于 OpenTelemetry 的 Trace、日志和监控。
- IAM、网络和运行安全。

Google Agent Registry 则集中登记和治理 Agent、MCP Server、工具和 Endpoint，支持发现、复用、权限边界及 A2A/MCP 互操作。

**启示：**

- Agent Registry 不只是列表，还要存储能力、Endpoint、协议、版本、所有者和安全要求。
- 运行时、上下文服务、质量评估和可观测性应解耦。
- 平台应支持本地 Agent 和外部 Agent 的统一逻辑视图。

### 2.4 Salesforce Agentforce

Agentforce 同时提供低代码 Builder、Agent Script、DX/CLI 和 Testing Center：

- Agent Blueprint 可由 YAML/脚本管理。
- Topic/Subagent、Action 和确定性表达式组合工作。
- 可配置 Agent User，其身份决定可访问的数据和操作。
- 测试可验证预期 Subagent、Action 和自然语言结果。
- 测试支持 UI、CLI、API 和 CI。
- 评测覆盖准确性、会话质量、子 Agent 识别、动作执行、知识检索、时延等。

**启示：**

- Agent 定义必须支持“可视化配置 + 可导出的声明式定义”。
- Evaluation Suite 应进入版本控制和 CI，而不是仅存在于页面。
- 路由正确率和工具选择正确率应成为独立指标。
- 测试默认不得直接污染生产业务数据。

## 3. 社会模拟与生产工作流

### 3.1 MiroFish

MiroFish 的核心链路是：

```text
种子材料
-> 知识图谱与记忆注入
-> 实体关系和 Persona 生成
-> OASIS 社会环境
-> 多轮群体交互和时序记忆
-> 报告生成
-> 与 Agent/世界深度交互
```

它的优势是：

- 从材料自动构造角色、关系和社会环境。
- Agent 拥有独立人格、行为逻辑和长期记忆。
- 用户可以从“上帝视角”注入变量。
- 仿真结果可以通过 Report Agent 查询。

它的目标是社会预测和群体涌现，不是稳定交付业务产物。因此 Agent Arena 可以借鉴其 Client、关系图、角色访谈和动态事件注入，但不能照搬其自由社会演化作为生产执行内核。

### 3.2 CAMEL 与 OASIS

CAMEL 将 Agent、Agent Society、Memory、Storage、Runtime、Benchmark、Retriever 和 Human-in-the-Loop 作为独立模块；OASIS 面向大规模社会交互模拟。

适合 Agent Arena 借鉴的部分：

- Persona、角色关系和有状态记忆。
- 环境事件对 Agent 行为的影响。
- 可插拔模型、工具、存储和检索。
- Critic Agent 与 Benchmark。

需要谨慎的部分：

- 大规模 Agent 数量不等于生产效果。
- 涌现式结果难以复现和验收。
- 社会模拟中的“自由行为”需要被生产流程的权限、预算和质量门约束。

### 3.3 MetaGPT

MetaGPT 将软件公司的 SOP 固化到产品经理、架构师、项目经理和工程师等角色团队中，核心表达为 `Code = SOP(Team)`。

**启示：**

- 高质量多 Agent 不只依赖角色提示词，更依赖可执行 SOP。
- 生产流模板应同时打包角色、任务、产物 Schema、检查规则和交接协议。
- Agent Arena 的模板单位不应只是单个 Prompt，而应是完整的“组织运行包”。

## 4. 协议与开放生态

### 4.1 MCP：Agent 到工具和数据

MCP 标准化 Agent/Client 对外部工具与资源的访问。其授权规范强调 OAuth、PKCE、资源受众绑定、短期 Token 和最小权限。

Agent Arena 应将 MCP Server 作为受治理工具源：

- 登记来源、版本、能力和风险级别。
- 工具按 Workspace、Agent、场景和运行授权。
- 高风险调用需要人工批准。
- 禁止 Token 透传和跨资源复用。
- 工具返回内容进入 Prompt 前进行注入风险处理。

### 4.2 A2A：Agent 到 Agent

A2A 的关键对象包括：

- `AgentCard`：身份、能力、技能、Endpoint 和认证要求。
- `Task`：有状态的长任务。
- `Message`：交互消息。
- `Artifact`：任务产生的正式交付物。
- Streaming/Push：异步状态和产物更新。

A2A 强调外部 Agent 可以保持内部实现不透明，只通过声明能力和交换任务、消息、产物进行协作。

Agent Arena 应在内部领域模型中保留兼容映射：

| Agent Arena | A2A |
| --- | --- |
| Agent Blueprint/Published Agent | Agent Card |
| Task Instance | Task |
| Structured Message | Message/Part |
| Artifact Version | Artifact |
| Run Event | Status/Artifact Update |

Agent Arena 的扩展层包括 Society、Policy、Debate、Evidence、Evaluation 和 Learning，这些不是 A2A 本身负责的内容。

## 5. 安全与治理

NIST AI RMF 使用 Govern、Map、Measure、Manage 四个持续函数管理 AI 风险，并强调测试、评估、验证和确认贯穿生命周期。OWASP Agentic Security Initiative 则关注 Agent 自主行动、工具滥用、身份权限、记忆污染、提示注入和级联失败。

Agent Arena 需要落实：

- 组织责任、Agent 所有者和审批者。
- 场景风险分级和允许的自主程度。
- Agent 与工具最小权限。
- 高风险动作的人工确认。
- 知识来源、证据和生成内容的 provenance。
- 发布前测试、运行监控、事件记录和事故复盘。
- 可随时暂停、撤销和隔离 Agent。

## 6. 对目标蓝图的新增约束

1. **资产化**：Agent、工具、知识、模板和评测都必须可登记、版本化和复用。
2. **双表达**：同时支持可视化配置与声明式文件。
3. **双运行语义**：自治协作与确定性工作流并存。
4. **双协议边界**：MCP 管工具，A2A 管外部 Agent。
5. **四阶段生命周期**：设计、测试、发布、运行。
6. **控制平面**：身份、权限、目录、策略、版本、预算和审计集中治理。
7. **结果优先**：Artifact 和 Evidence 是主对象，聊天只是过程。
8. **评测前置**：路由、动作、知识、结果、风险、成本和时延均可测试。
9. **社会增强**：在工作流之上增加关系、权责、挑战、仲裁和声誉。
10. **人类主权**：用户始终可以确认、暂停、修订、接管和否决。

## 7. 参考资料

- [Microsoft Copilot Studio Connected Agents](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/authoring-add-other-agents)
- [Microsoft Copilot Studio Add Other Agents](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-add-other-agents)
- [IBM Agentic Orchestration](https://www.ibm.com/products/watsonx-orchestrate/multi-agent-orchestration)
- [IBM Understanding Agent Orchestration](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=agents-understanding-agent-orchestration)
- [Google Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/generative-ai/docs/reasoning-engine/overview)
- [Google Agent Registry](https://docs.cloud.google.com/agent-registry/overview)
- [Salesforce Agentforce Testing Center](https://help.salesforce.com/s/articleView?id=ai.agent_testing_center.htm&language=en_US&type=5)
- [Salesforce Agentforce DX](https://developer.salesforce.com/docs/einstein/genai/guide/agent-dx-reference.html)
- [MiroFish](https://github.com/666ghj/MiroFish)
- [CAMEL](https://github.com/camel-ai/camel)
- [OASIS](https://github.com/camel-ai/oasis)
- [MetaGPT](https://github.com/FoundationAgents/MetaGPT)
- [A2A Protocol](https://a2a-protocol.org/latest/)
- [A2A Specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [MCP Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
- [OWASP Agentic AI Threats and Mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)

