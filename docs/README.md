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
- [项目范围与 Client 需求](02-requirements/project-scope.md)
- [首个生产流：产品需求评审与方案攻防](02-requirements/first-production-flow.md)
- [ADR-0001：文档作为项目过程记录](03-decisions/ADR-0001-documentation-as-project-record.md)
- [ADR-0002：平台命名为 Agent Arena](03-decisions/ADR-0002-product-name.md)
- [Agent 角色与协作对抗协议](04-design/agent-roles-and-protocol.md)
- [系统架构、事件模型与运行状态机](04-design/system-architecture.md)
- [Client 信息架构与交互设计](04-design/client-information-architecture.md)
- [MVP 纵向切片实现记录](05-implementation/mvp-vertical-slice.md)
- [2026-07-23 工作日志](journal/2026-07-23.md)

## 后续计划文档

- 评估指标与测试方案
- 真实 Agent 与模型网关实现
- 知识检索与证据索引实现
- 数据库与持久化设计
- 具体示例产品需求与实验结果
