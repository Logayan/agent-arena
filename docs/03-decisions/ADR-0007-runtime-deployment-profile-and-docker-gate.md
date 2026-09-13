# ADR-0007：按当前运行环境执行 Runtime 验证

- 状态：已确认
- 日期：2026-09-11
- 背景：Claude Agent SDK G3 技术探针

## 1. 问题

G3 原计划把 Docker Linux 冷启动列为阶段完成条件。但当前实际运行环境是 Windows，Docker Desktop 可能因管理员策略、虚拟化或服务权限无法运行。把当前机器无法运行 Docker 解释为 Claude Runtime 不可用，会把“未具备某种额外部署环境”错误提升为“当前环境技术不可行”。

## 2. 分析结论

测试必须识别任务当前所处的真实环境，并在该环境中验证实际执行路径。当前环境是 Windows，因此应以 Windows 上的真实 SDK、CLI、进程、文件和权限行为作为本轮技术探针结论。当前已经取得以下证据：

- SDK 和内置 Claude Code CLI 可运行；
- 当前 GPT Endpoint、认证和 `gpt-5.6-sol` 可用；
- 文件、编辑、命令、Skill、`CLAUDE.md`、Session resume、实时事件、MCP 和受控子 Agent 可用；
- Workspace 权限回调可拒绝越界读取。

这些证据只说明 Claude Runtime 在当前 Windows 环境可行，不代表产品架构、发布策略或支持优先级改为 Windows 优先。Linux、容器或其他环境应在实际具备相应运行条件时分别验证。

## 3. 提议决策

1. 不设“Windows 优先”或“Docker 优先”的隐含产品方向。
2. 每轮验证先识别当前 OS、架构、可用运行时和权限，再执行与当前环境匹配的真实测试。
3. 当前 G3 按 Windows 实际环境判定 SDK 技术路径通过；Docker 未运行记录为“当前环境未提供该附加执行条件”，不是当前 SDK 路径失败。
4. Docker 构建、Linux 非 root、冷启动和进程回收仍保留，在真正进行 Linux/容器部署或发布验收时执行。
5. 不删除现有 Dockerfile/Compose，也不降低未来容器部署要求。
6. 当前环境生产切换仍不得绕过两个真实 P0 缺口：
   - 取消/超时必须终止 Bash、PowerShell 和子 Agent 进程树；
   - Bash 和 Agent 工具环境不得读取模型 Provider 密钥。

## 4. 影响

该决策只修正验证方法，不指定产品部署优先级。G4 Claude Runtime Adapter 应保持跨平台设计，并首先在当前实际可运行的 Windows 环境完成实现和验证；进入其他环境时再补对应环境证据。

这不等于现在直接切换生产 Runtime，也不自动授权进入 G4。Adapter 实现、合同测试、同题能力对照和用户确认仍然必须完成。
