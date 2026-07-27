# Agent Arena 平台路线图

- 版本：0.1
- 日期：2026-07-24

## 阶段 0：现有纵向原型

状态：已完成基础原型

目标：

- 验证 Client、事件流和协作/攻防展示。

当前已有：

- Client 原型
- 事件契约
- 固定流程模拟器
- 角色和协议设计

该阶段不再继续扩充固定 Demo。

## 阶段 1：场景与 Agent 配置

目标：

- 移除首页固定 `/api/demo`
- 新建 Workspace 和 Scenario
- 配置 Agent 蓝图
- 配置模型、工具、权限和预算
- 保存 WorkflowDefinition

交付：

- Scenario Builder
- Agent Library
- Agent 配置 API
- WorkflowDefinition Schema
- PostgreSQL 持久化

## 阶段 2：真实多 Agent 最小闭环

目标：

```text
需求 Agent
-> 方案 Agent
-> 红队 Agent
-> 修订
-> 裁判 Agent
```

交付：

- Model Gateway
- Agent Worker
- Orchestrator
- 结构化消息
- ArtifactVersion
- 缺陷和门禁
- Token、成本和时间统计

## 阶段 3：知识与证据底座

目标：

- Workspace 知识隔离
- 文件解析
- 关键词和向量检索
- 证据引用
- 事实、推断、假设和冲突
- 运行经验候选写回

交付：

- Knowledge Hub
- KnowledgeSpace API
- Evidence Graph
- Retrieval Service
- Memory Policy

## 阶段 4：课题验收案例

目标：

- 从需求开发中选择一个具体需求。
- 通过通用平台创建场景。
- 通过 Agent Library 配置角色。
- 通过 Workflow Studio 配置流程。
- 使用真实 Agent 完成协作、对抗和评估。
- 比较单 Agent 和多 Agent。

案例不得写死到平台核心。

## 阶段 5：Agent 社会体系

目标：

- 团队和组织关系
- 社会制度和权限
- 协商与仲裁
- 声誉和历史能力
- 可复用 SocietyTemplate

交付：

- Society Designer
- Policy Engine
- Reputation Model
- Arbitration Protocol
- Agent Blueprint Registry

## 阶段 6：工作流工厂

目标：

- 根据自然语言场景生成工作流草案
- 推荐 Agent 团队
- 推荐协作和对抗模式
- 推荐评估和人工节点
- 静态检查后由用户确认

交付：

- Scene Interpreter
- Role Planner
- Workflow Planner
- Adversary Planner
- Evaluation Planner
- Workflow Studio

## 阶段 7：评估与持续优化

目标：

- 单 Agent 与多 Agent 基线
- 多次运行稳定性
- 提示词、模型和流程实验
- 自动生成优化建议
- 方法库和模板库

交付：

- Evaluation Lab
- Benchmark Suite
- A/B Run
- Workflow Analytics
- Template Marketplace

## 近期三次迭代

### Iteration 1

- Workspace
- Scenario 创建
- Agent 蓝图 CRUD
- Agent 配置页
- PostgreSQL

### Iteration 2

- 真实四 Agent 闭环
- 模型网关
- 产物和消息持久化
- 红队与裁判动态执行

### Iteration 3

- Knowledge Space
- 文件接入和检索
- 证据引用
- 单 Agent 与多 Agent 对比实验

## 课题验收节点

课题不是当前架构的驱动力，而是平台阶段能力的验收。

当以下内容完成时，即可形成课题交付版本：

- 一个真实生产流
- 至少 4 个真实 Agent
- 一次协作和一次对抗闭环
- 可运行 Client
- 流程图与角色说明
- 单 Agent 和多 Agent 的质量、时间、成本对比
- README 和演示说明
