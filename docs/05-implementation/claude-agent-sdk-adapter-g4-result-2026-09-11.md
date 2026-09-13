# Claude Agent SDK Adapter G4 实现结果

- 状态：完成，等待 G5 同题能力对照授权
- 日期：2026-09-11
- 当前环境：Windows `win32/x64`
- 默认生产 Runtime：OpenClaw（未切换）
- Claude Agent SDK：`0.3.268`
- 内置 Claude Code：`2.1.268`
- 真实验证模型：当前平台加密配置中的 `gpt-5.6-sol`
- 正式证据：`../../experiments/claude-agent-sdk-probe/results/g4-adapter-20260911T144637Z/result.json`

## 1. 完成结论

G4 已完成 Claude Agent SDK Runtime Adapter 的实现、注册、合同测试与当前 Windows 环境真实 E2E。Claude Adapter 已满足统一 `AgentRuntimePort`，但只作为非默认实现注册；平台默认执行路径、API 兼容语义、数据库默认值、OpenClaw 文件和前端入口均未切换。

G3 发现的两个 P0 缺口已经关闭：

1. 工程命令不再使用可见 Provider 凭据的内置 Bash，而是通过同进程 MCP Workspace Gateway 在清洗环境中执行；真实命令确认 Provider Key/Token 变量不可见。
2. Python Adapter 和 Node Bridge 同时监管进程生命周期；Windows 取消真实长命令后，Bridge、命令 Shell 和后代 PowerShell 进程树均被终止，没有产生迟到文件。

G4 可以进入 G5 门禁，但不得据此直接切换生产默认 Runtime。G5 仍需使用同一能力集对 OpenClaw 与 Claude Adapter 做完整差异验证。

## 2. 实现内容

### Python Runtime Adapter

`server/app/claude_code_runtime.py` 实现：

- `ClaudeCodeRuntime`、统一错误分类和 Health；
- Run 与 Agent Workspace 隔离；
- Persona、身份、行为规范和 Memory 投影到 `CLAUDE.md`；
- Skill 投影到 `.claude/skills/<skill>/SKILL.md`，并清理失效 Skill；
- 平台 `session_key` 到 Claude SDK Session ID 的持久映射与 `resume`；
- NDJSON 流式动作接收、公共 Action 归一化和公开回调；
- `delivery/` 文件变化、提交清单和最终交付树晋升；
- Provider 错误、超时和取消处理；
- Windows `taskkill /T /F` 与非 Windows Process Group 回收；
- Provider Token 和公开事件脱敏，保留正常 token 用量数字。

### Node SDK Bridge 与 MCP Workspace Gateway

`server/claude_agent_runtime/bridge.mjs` 实现：

- 通过 Claude Agent SDK `query()` 调用当前模型 Endpoint；
- 关闭全部内置工程工具，使用 `toolAliases` 将 Read/Write/Edit/Bash 指向私有 MCP 工具；
- `strictMcpConfig=true`，忽略未获准的磁盘 MCP 配置；
- Read 只允许 Agent Workspace；Write/Edit 只允许 `delivery/`；路径段中的符号链接被拒绝；Bash 固定在 `delivery/`；
- Bash 使用环境白名单，不继承 Provider Key、Token、Secret、Password、Auth 或 Credential 变量；
- 命令超时、输出上限、子进程跟踪和进程树终止；
- SDK assistant/tool/result 事件映射为公共 `progress/tool_call/tool_result`；
- Provider Token 只通过 stdin 进入 Bridge 内存与 Claude CLI 请求环境，不写入 Runtime 策略文件。

### 注册、测试和依赖

- `server/app/agent_runtime_registry.py` 注册 `claude_code`，默认仍为 `openclaw`；
- `server/tests/runtime_contract/test_claude_code_runtime_contract.py` 增加 6 项 Adapter 合同测试；
- `scripts/verify-claude-code-runtime-g4.py` 增加可重复的真实 E2E 采集；
- `server/claude_agent_runtime/package.json` 和 lockfile 固定 SDK 与 Zod 依赖。

## 3. 验证结果

### 静态与依赖检查

- Python `py_compile`：通过；
- Node `--check`：通过；
- `npm ls --depth=0`：通过；
- 实际依赖：Claude Agent SDK `0.3.268`、Zod `4.6.2`。

### 合同与全量回归

- Claude Adapter 合同测试：`6 passed`；
- Runtime Port 与 Claude Adapter组合检查：`13 passed, 1 warning`；
- 全量后端：`71 passed, 1 warning`，最终复跑耗时 `48.22s`；
- Warning 是既有 openpyxl 工作簿默认样式提示，与 Runtime 迁移无关。

### 当前环境真实 E2E

正式证据 `g4-adapter-20260911T144637Z` 的 15 项检查全部通过：

- SDK 与 Claude Code 版本固定；
- Adapter Health 与配置状态正常；
- Write、Bash、Read 均通过 MCP Gateway 实际执行；
- 正式文件内容和 SHA-256 可核验；
- 普通 Windows PowerShell 命令成功；
- Bash 子进程不可见 Provider 凭据环境变量；
- tool_call/tool_result 在最终结果前流式到达；
- Session resume 返回精确标记；
- 取消长命令后记录到的后代 PowerShell PID 已不存在；
- 没有产生取消后的迟到结果文件；
- 公开 Action 和新增范围扫描均未发现明文 API Key。

本次真实正常回合记录用量：输入 `3563`、输出 `340` tokens。密钥只从现有加密平台配置读取，未进入命令行、结果 JSON 或仓库源码。

## 4. 能力保持边界

本阶段只替换单 Agent Runtime Adapter 的底层实现候选。以下能力仍由平台原有代码负责，G4 未改写：

- Workflow、Task、Run、Attempt、Checkpoint 和预算；
- 多 Agent 并发、依赖、Judge、返工、暂停和恢复；
- Memory、知识授权、Artifact、Evidence 和审计；
- Matrix/Synapse、外部介入、API 和 Client 体验；
- 历史 OpenClaw 事件与数据读取。

这符合“只把 OpenClaw 的能力用 Claude Code SDK 替换，其他保持不变”的范围约束。

## 5. G5 必须继续验证

G4 只证明 Adapter 自身可用，没有完成最终能力等价判定。G5 必须补齐：

1. RTC-001 至 RTC-032 同题双跑与逐项差异；
2. 真实多 Agent、Judge、返工、暂停、恢复、预算和取消；
3. 工程与非工程 Agent 权限等价；
4. 文件提交、晋升、迟到结果和路径逃逸安全；
5. 性能、token 用量、费用和失败分类差异；
6. 当前 Windows 环境的完整平台 E2E；实际部署到 Linux/容器时再补对应环境证据。

在用户确认 G5 计划和范围前，不切换默认 Runtime、不删除 OpenClaw。
