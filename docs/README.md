# 项目文档索引

本文档目录是项目的统一过程记录。需求讨论、框架调研、架构决策、实现过程和验证结论均应在这里保留，不只存在于对话中。

## 文档规则

1. 外部系统和技术调研写入 `01-research/`。
2. 已确认需求、待确认事项和范围变更写入 `02-requirements/`。
3. 重要技术或产品取舍使用 ADR，写入 `03-decisions/`。
4. 每次实质性讨论、实现或验证写入 `journal/YYYY-MM-DD.md`。
5. 文档应区分事实、推断、建议和已确认决策。
6. 代码实现后需记录涉及文件、验证命令、结果和遗留问题。
7. 不保存模型不可见的内部推理过程；保存对项目有用、可复核的分析依据、结论和决策记录。

## 当前文档

- [MiroFish 框架调研](01-research/mirofish-framework-analysis.md)
- [多 Agent 平台竞品与行业实践调研](01-research/multi-agent-platform-competitor-analysis.md)
- [企业级 Agent 平台与社会模拟补充调研](01-research/enterprise-agent-platform-followup.md)
- [OpenClaw 与多 Agent 技术方案选项分析](01-research/openclaw-and-multi-agent-technical-options.md)
- [与江湖 Online 相似的多 Agent 开源方案调研](01-research/similar-open-source-multi-agent-projects.md)
- [项目范围与 Client 需求](02-requirements/project-scope.md)
- [首个生产流：产品需求评审与方案攻防](02-requirements/first-production-flow.md)
- [Agent Arena 平台愿景与课题边界](02-requirements/platform-vision.md)
- [Agent Arena 用户需求基线](02-requirements/user-requirements-v1.md)
- [Agent Arena 用户需求基线 v2](02-requirements/user-requirements-v2.md)
- [江湖 Online 产品需求文档 v1.0](02-requirements/jianghu-online-prd-v1.0.md)
- [江湖 Online 原始愿景与比赛约束](02-requirements/jianghu-online-origin-requirements.md)
- [江湖 Online 系统需求规格说明书 v1.0](02-requirements/system-requirements-v1.md)
- [江湖 Online 完整版系统需求规格说明书 v2.0（待确认）](02-requirements/system-requirements-v2.md)
- [ADR-0001：文档作为项目过程记录](03-decisions/ADR-0001-documentation-as-project-record.md)
- [ADR-0002：平台命名为 Agent Arena](03-decisions/ADR-0002-product-name.md)
- [ADR-0003：平台定位为多 Agent 平台](03-decisions/ADR-0003-platform-over-demo.md)
- [ADR-0004：平台优先，课题案例仅作为验收](03-decisions/ADR-0004-platform-first-demo-as-acceptance.md)
- [ADR-0005：领域运行时与可插拔 Agent 执行适配层](03-decisions/ADR-0005-domain-runtime-and-pluggable-agent-adapters.md)
- [Agent 角色与协作对抗协议](04-design/agent-roles-and-protocol.md)
- [系统架构、事件模型与运行状态机](04-design/system-architecture.md)
- [Harness、Loop 与 Graph Engineering 设计基线](04-design/harness-loop-graph-engineering.md)
- [长期操作型 Agent 与 OpenClaw Adapter 设计](04-design/operational-agent-and-openclaw-adapter.md)
- [江湖 Online 系统详细设计说明书 v1.0](04-design/detailed-design-v1.md)
- [Client 信息架构与交互设计](04-design/client-information-architecture.md)
- [Agent 社会体系与工作流工厂](04-design/agent-society-and-workflow-factory.md)
- [Agent Arena 目标产品蓝图](04-design/target-product-blueprint.md)
- [MVP 纵向切片实现记录](05-implementation/mvp-vertical-slice.md)
- [多 Agent 协作与对抗体现在哪里](05-implementation/collaboration-and-adversarial-behavior.md)
- [Agent Arena 平台路线图](06-roadmap/platform-roadmap.md)
- [2026-07-23 工作日志](journal/2026-07-23.md)
- [2026-07-24 工作日志](journal/2026-07-24.md)
- [2026-07-27 工作日志](journal/2026-07-27.md)
- [2026-07-28 工作日志](journal/2026-07-28.md)
- [2026-07-29 工作日志](journal/2026-07-29.md)

## 后续计划文档

- 评估指标与测试方案
- 真实 Agent 与模型网关实现
- 知识检索与证据索引实现
- 数据库与持久化设计
- 具体示例产品需求与实验结果
