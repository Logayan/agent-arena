# Agent Runtime 能力基线与防回退测试计划

- 状态：范围已确认，G1 执行中；真实能力受 Provider 余额阻塞
- 日期：2026-09-11
- 目标：在 OpenClaw 被移除前冻结当前真实能力，并让 Claude Code SDK 接受完全相同的可观察能力验收
- 约束：G1 已获授权；任何新的付费真实用例仍需先确认模型和费用，G1 完成前不得进入 G2

## 1. 测试原则

1. 先测当前 OpenClaw，再实现 Claude Code SDK Adapter。
2. 同一测试集面向统一 Runtime 合同，不把 OpenClaw 或 Claude 私有字段作为业务断言。
3. Mock 测精确协议，真实 E2E 测实际能力，二者不能互相替代。
4. 不逐字比较模型回答，比较可观察结果、证据、文件、事件、权限和终态。
5. 测试数据不得包含真实 Token、用户私密文件或生产数据库。
6. 每次真实运行记录模型、SDK/Runtime 版本、配置指纹、Token、费用、时延和随机性来源。
7. “其他保持不变”作为硬门禁：Runtime 之外的产品能力、接口行为、数据语义、Matrix/Synapse 和用户体验不得借迁移发生删减或重定义。

## 2. 测试分层

### L0：静态能力盘点

- Runtime API、环境变量、Docker 依赖、数据库字段、事件类型、前端接口和验证脚本。
- 输出当前能力矩阵和迁移影响文件清单。

### L1：Runtime 合同测试

- 使用确定性 Fake Provider 或捕获的脱敏事件验证精确 Schema。
- 不访问外网，不消耗模型费用。
- OpenClaw Adapter 和 Claude Adapter 必须执行同一组参数化测试。

### L2：真实单 Agent E2E

- 使用真实模型完成文本任务和工程任务。
- 验证身份、Skills、Memory、工具、文件、测试和最终产物。

### L3：真实多 Agent E2E

- 验证独立贡献、公开消息、团队合议、Judge 退回和再次通过。
- 沿用并泛化 `scripts/verify-real-openclaw-e2e.py` 的闭环，但不能只改脚本名称。

### L4：故障与安全测试

- 超时、取消、暂停、API 重启、网络错误、模型限流、工具失败、无效输出、孤儿子进程、迟到结果。
- 路径穿越、符号链接、秘密泄露、跨 Agent 读取、未批准外部写操作、命令注入。

### L5：性能和成本对照

- 时延、Token、费用、工具轮次、进程内存和并发资源。
- 性能只设合理阈值，不要求两种 Runtime 完全一致。

## 3. 核心测试集

| ID | 能力 | 核心断言 |
| --- | --- | --- |
| RTC-001 | 健康检查 | 能识别运行时版本、不可用原因和模型配置状态 |
| RTC-002 | Agent 投影 | 身份、Persona、规范、Memory、Skills 按 Agent 版本隔离 |
| RTC-003 | Run 隔离 | 两个 Run 的 Session 与临时状态互不污染 |
| RTC-004 | Agent 隔离 | 两个 Agent 不能读取对方私有文件和 Session |
| RTC-005 | 模型覆盖 | 节点 tier 对应的模型被实际使用，缺失时明确失败 |
| RTC-006 | 普通文本回合 | 返回非空公开内容、Session ID、模型和用量 |
| RTC-007 | 实时动作 | tool_call/tool_result 在回合完成前可观测 |
| RTC-008 | 思维保护 | thinking、隐藏摘要和内部 Prompt 不出现在公共事件 |
| RTC-009 | 密钥脱敏 | Token、密码和敏感环境变量不进入事件、日志和产物 |
| RTC-010 | 工程工具 | Agent 可在授权 Workspace 读写文件、执行命令和测试 |
| RTC-011 | 非工程权限 | 非工程 Agent 无法执行未授权写文件或 Shell |
| RTC-012 | 文件变更 | created/modified/deleted 的路径、哈希和大小准确 |
| RTC-013 | 工程提交 | 多人贡献只公开声明的交付文件，不公开私有上下文 |
| RTC-014 | 正式晋升 | Lead 已测试的完整 delivery 树准确晋升到 Run code |
| RTC-015 | Seed | 上游代码副本正确进入独立 Workspace，主工作区不被修改 |
| RTC-016 | 多 Agent 并行 | 参与者使用独立 Session 并产生独立贡献 |
| RTC-017 | 公共通信 | 消息有发送者、接收者、轮次和类型，不含私有 Memory |
| RTC-018 | 合议 | Lead 能读取公共贡献并形成可追溯正式提交 |
| RTC-019 | 独立 Judge | Judge 使用独立身份、Session 和 Prompt，并可真实复验 |
| RTC-020 | 返工闭环 | revise 只重开目标节点，历史 Artifact 保留新版本 |
| RTC-021 | Memory 写回 | 完成后只写回参与 Agent 的私有经历 |
| RTC-022 | 暂停恢复 | 边界状态明确，不重复提交 Artifact |
| RTC-023 | 取消 | 主回合和子任务被终止，迟到结果不晋升 |
| RTC-024 | 超时重试 | 自动重试次数有限，Attempt/Session 隔离 |
| RTC-025 | API 重启恢复 | 已完成节点保留，中断节点安全重放 |
| RTC-026 | 用量 | 主 Agent、子 Agent 和辅助调用的统计口径可解释 |
| RTC-027 | MCP | 获准 MCP 可用，未授权 MCP 不出现在工具列表 |
| RTC-028 | 子 Agent | 深度、并发、模型、工具和预算不超过父级政策 |
| RTC-029 | 网络 | Search/Fetch 受域名和外部访问策略限制 |
| RTC-030 | Matrix 介入 | 平台筛选后的公开介入可进入节点，私有历史不被注入 |
| RTC-031 | Provider 不兼容 | OpenAI Responses 等不兼容配置明确路由或明确拒绝 |
| RTC-032 | Docker 冷启动 | 干净镜像可启动、发现 SDK 二进制并执行最小回合 |

## 4. 基线输出格式

建议落盘目录：

```text
server/tests/runtime_contract/
  cases/
  fixtures/
  test_runtime_contract.py
  test_runtime_security.py

.data/verification/runtime-baselines/
  openclaw/<baseline-id>/
    manifest.json
    normalized-events.jsonl
    artifacts.json
    file-manifest.json
    metrics.json
    report.md
```

`.data` 中的真实输出不提交 Git；Git 只保存脱敏、小尺寸、可重复使用的 fixtures 和基线 manifest Schema。

## 5. 归一化规则

比较时忽略：

- 随机 Run、Session、Tool Call ID；
- 绝对临时路径；
- 时间戳的精确值；
- 模型自然语言的逐字差异；
- Provider 特有但不影响平台语义的元数据。

必须严格比较：

- 事件顺序约束和终态；
- 权限允许/拒绝结果；
- 文件路径、动作、哈希和交付树；
- Artifact 版本、Judge 结果和返工目标；
- 公共与私有信息隔离；
- 取消、超时、重试和恢复语义；
- 用量字段是否完整且口径有记录。

## 6. 通过门禁

Claude Code SDK 切换候选必须满足：

- L1 合同测试 100% 通过；
- L2/L3 关键真实场景全部成功，允许模型内容不同但合同不变；
- L4 高风险安全用例 100% 通过；
- 不得丢失 RTC-001 至 RTC-032 中任何已确认的 P0 用例；
- OpenClaw 能力必须由 Claude Code SDK、Adapter、平台服务或 MCP 得到等效替换，不能以“SDK 不原生支持”为理由删除；
- 非 OpenClaw 能力的回归结果必须与迁移前一致；
- 不得出现秘密泄露、跨 Agent 访问、重复正式产物或取消后晋升；
- 性能或成本明显恶化时必须形成单独批准记录；
- 能力差异报告经过用户确认。

## 7. 执行顺序

1. 用户确认测试范围、模型和费用上限。
2. 创建 L0/L1 测试代码与 Schema。
3. 运行现有单测，修复测试本身的确定性问题。
4. 在 OpenClaw 仍可用时运行 L2/L3/L4 基线。
5. 冻结基线 manifest 和脱敏 fixtures。
6. 用户审阅基线报告。
7. 才允许开始 Claude Code SDK Adapter 实现。
8. 使用相同测试集复跑并生成差异报告。

## 8. 尚待确认

- 真实基线允许使用哪个模型和 Endpoint。
- 单次及整套测试的 Token/费用上限。
- 是否将 OpenAI Responses 作为同一 Runtime 合同中的第二 Adapter。
- Matrix 介入测试是否进入本次 P0。
- 性能回退的可接受阈值。
