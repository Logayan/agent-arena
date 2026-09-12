# 完整生产流演示：单 Agent 与多 Agent 对照实验

这是仓库内置的可运行演示案例，不包含预制 Run、Mock 结果、用户数据或模型凭据。

启动平台后进入“实战擂台”，安装案例会创建或复用：

- 单 Agent 生产基线：一位全栈交付工程师完成真实代码、README 和自动化测试；独立裁判只盲审，不参与生产。
- 多 Agent 协作/对抗流：需求与架构并行，双人隔离开发，质量与红队并行挑战，整改后由同一独立裁判验收；不通过会自动 Loop。
- 一支可复用团队和八位拟人化 OpenClaw Agent。人物、团队和 WorkflowVersion 都会进入平台正式资产列表。

两组使用同一任务、模型配置、运行预算和隐藏验收集。点击启动后会创建两个独立 Run、两个隔离代码目录，并产生真实 Token 和费用。

## 真实验收任务

交付一个仅依赖 Python 标准库的事件优先级评估器，固定核心文件和函数契约。两个 Run 都必须创建真实文件、执行真实命令和自动化测试，并接受平台隐藏的 9 项边界/异常测试。

## 指标口径

| 指标 | 来源 | 解释 |
|---|---|---|
| 隐藏验收通过率 | Run 代码目录 + 平台隐藏测试 | 检查规则正确性、边界和非法输入处理 |
| 问题发现率 | 非裁判产物、公开挑战与执行事件 | 统计预定义风险主题在生产阶段是否被显式发现 |
| 产出完整度 | 文件、测试、节点产物和裁判证据 | 检查源码、README、测试、正式产物和裁判通过 |
| 综合质量 | 60% 隐藏验收 + 25% 完整度 + 15% 裁判评分 | 用于同一轮内部对比，不作为跨任务通用评分 |
| 真实耗时 / Token | Run 持久化记录 | 展示多 Agent 提升质量时付出的时延与模型成本 |
| 人工耗时估算 | 公开公式 | 人工参考 180 分钟；启动复核 3 分钟、每次介入 5 分钟、终态未通过处置 10 分钟。不是工时系统实测值 |

结果页面不会预填“多 Agent 一定更好”。只有两个真实 Run 都进入终态后，平台才计算质量提升、问题发现率变化、完整度变化以及耗时和 Token 代价。

## API

- `GET /api/platform/showcases/production-flow-comparison`
- `POST /api/platform/showcases/production-flow-comparison/install`
- `POST /api/platform/showcases/production-flow-comparison/comparisons`
- `POST /api/platform/showcases/production-flow-comparison/comparisons/{comparison_id}/start`
- `GET /api/platform/showcases/production-flow-comparison/comparisons/{comparison_id}`

