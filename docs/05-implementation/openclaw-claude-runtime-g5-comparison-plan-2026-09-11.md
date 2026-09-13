# OpenClaw 与 Claude Agent SDK Runtime G5 同题能力对照计划

- 状态：已授权，执行中
- 日期：2026-09-11
- 默认生产 Runtime：OpenClaw（G5 保持不变）
- 对照对象：OpenClaw 2026.7.1-2 与 Claude Agent SDK 0.3.268 / Claude Code 2.1.268
- 模型配置：使用当前平台加密保存的 gpt-5.6-sol 配置，不在命令行或证据中保存 Token

## 1. 阶段目标

使用 RTC-001 至 RTC-032 的同一可观察能力口径，对 OpenClaw Adapter 与 Claude Adapter 做合同、真实单 Agent、真实多 Agent、故障安全、平台能力和性能成本对照，判断 Claude Adapter 是否存在阻止进入 G6 默认路径切换的能力回退。

G5 只形成测试、证据和差异结论，不修改默认 Runtime、不改数据库默认值、不删除 OpenClaw、不修改产品 API 或前端语义。

## 2. 对照方法

### A. 统一合同测试

对两种 Adapter 使用同一组参数化测试，比较：

- Health、身份/Memory/Skill 投影、Run/Agent/Session 隔离；
- 模型覆盖、公开动作、思维保护、敏感字段脱敏；
- 工程与非工程权限、文件变化、提交、晋升和 Seed；
- 用量字段、错误分类和 Provider 路由。

不比较 Runtime 私有控制文件名称，只比较平台可观察语义。

### B. 真实单 Agent 同题双跑

两种 Runtime 使用同一 Agent、同一模型配置和同一确定性任务：

- 创建同路径、同内容文件；
- 执行当前 Windows 环境的普通 PowerShell 命令；
- 采集流式 tool_call/tool_result、文件哈希、Session、用量和时延；
- 检查 Provider 凭据不进入公开事件和交付文件。

### C. 真实平台多 Agent 双跑

在隔离数据库和 Workspace 中分别执行：

1. 文本协作、公开消息、Lead 合议、独立 Judge、退回和再次通过；
2. 多人工程贡献、公开提交、Lead 合并、测试和便携交付。

平台测试运行时可在独立测试进程内临时选择 Adapter，但仓库和生产默认值保持 OpenClaw。

### D. 故障与安全

- 取消、超时、重试、暂停恢复、API 恢复和迟到结果；
- 跨 Agent 访问、路径穿越、符号链接、未授权 MCP、凭据环境、非工程写入和 Shell；
- 网络策略与受控子 Agent；
- Matrix 只验证平台公开介入边界，不改变现有 Bridge。

### E. 性能和成本

记录真实回合的时延、输入/输出/cache tokens、工具轮次和文件结果。性能差异只做事实记录；若 Claude 出现明显成本或时延恶化，单独列为进入 G6 的批准项。

## 3. RTC 判定

每项 RTC 只允许以下状态：

- passed：两种 Runtime 在当前已启用范围内均满足；
- passed_by_platform：能力由平台层保持，与 Adapter 无关，已有回归证据；
- conditional：当前实际环境不具备目标部署面，只能保留后续环境门禁；
- failed：Claude 相比 OpenClaw 存在可观察 P0 回退；
- not_enabled：OpenClaw 理论能力在当前产品也未启用，不得误判为迁移回退。

P0 不允许以 unknown 或无证据状态通过。

## 4. 通过门禁

G5 通过必须同时满足：

1. RTC-001 至 RTC-032 全部登记状态、证据和能力归属；
2. 当前产品已启用的 P0 能力无 Claude 回退；
3. 真实单 Agent 双跑全部成功；
4. 真实文本多 Agent 与工程多 Agent 的 Claude 路径通过，且平台语义与 OpenClaw 基线一致；
5. 取消、凭据、路径和私有数据安全门禁通过；
6. 全量后端回归通过；
7. 明文 Token 扫描通过；
8. 差异、条件项和 G6 风险形成正式文件；
9. 用户确认差异报告后才可进入 G6。

## 5. 环境口径

本轮识别并测试当前真实环境 Windows win32/x64。这不代表产品采用 Windows 优先策略。RTC-032 在当前环境验证本地 Node/SDK Runtime 发现与冷启动；Linux 或容器证据在实际部署到对应环境时补齐，不因当前 Docker 不可用而伪造结果。

## 6. 预期产物

- 参数化 Runtime 对照测试；
- 真实双跑采集脚本与脱敏证据；
- RTC-001～RTC-032 能力矩阵；
- 性能与用量对照；
- G5 正式差异报告；
- 路线图、ADR、日志和文档索引更新。
