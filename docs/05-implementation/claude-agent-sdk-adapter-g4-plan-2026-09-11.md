# Claude Agent SDK Adapter G4 实现计划

- 状态：已完成，等待 G5 授权
- 日期：2026-09-11
- 默认生产 Runtime：OpenClaw（本阶段保持不变）
- 目标：实现满足 `AgentRuntimePort` 的 Claude Agent SDK Adapter，并关闭 G3 发现的安全与生命周期缺口

## 1. 阶段边界

G4 只实现和注册 Claude Adapter，不修改平台默认 Runtime，不迁移数据库默认值，不删除 OpenClaw，不修改前端产品入口。真实验证通过后停在 G5 同题能力对照门禁。

## 2. 实现结构

| 组件 | 职责 |
| --- | --- |
| `server/app/claude_code_runtime.py` | Python `AgentRuntimePort` 实现、Workspace、Session 映射、流式事件、文件变化和进程树监管 |
| `server/claude_agent_runtime/bridge.mjs` | Claude Agent SDK Query 桥接与 SDK 消息归一化 |
| `server/claude_agent_runtime/package.json` | 固定 SDK 版本及独立依赖 |
| MCP Workspace Gateway | Read/Write/Edit/Bash 的路径、环境、超时和输出边界 |
| Runtime Registry | 注册 `claude_code`，但不设为默认 |

## 3. 安全设计

1. Provider Token 只进入 Node Bridge 与 Claude CLI 请求环境。
2. 不开放 SDK 内置 Bash；Agent 工程命令通过 MCP Gateway 执行。
3. MCP Bash 使用清洗后的环境，删除名称包含 key、token、secret、password、auth、credential 的变量。
4. Read 只能读取 Agent Workspace；Write/Edit 只能修改 `delivery/` 正式候选区；Bash 固定在 `delivery/` 工作。
5. 公开事件只输出白名单字段并再次执行 Token 脱敏。
6. 取消、超时和 API Task cancellation 都终止 Node Bridge 及全部后代进程。

## 4. 能力映射

- 身份、Persona、规范和 Memory 投影到 Agent Workspace 的 `CLAUDE.md`；
- Skills 投影到 `.claude/skills/<skill>/SKILL.md`；
- 平台 `session_key` 映射 SDK Session ID，后续通过 `resume`；
- SDK assistant text 映射 `progress`；tool use/result 映射公共 Runtime Action；
- SDK result 映射公共 content、usage 和 model；
- `delivery/` 文件快照、公开提交与完整交付树晋升保持现有语义；
- 子 Agent 默认关闭，后续只按平台节点政策显式开放。

## 5. 验证

1. 无网络合同测试：Port、注册表、同步投影、Session、动作、文件和错误；
2. 凭据隔离测试：MCP Bash 不可见 Provider Token；
3. 取消/超时测试：后代进程不残留，Workspace 可释放；
4. 当前环境真实 E2E：使用加密保存的当前 GPT 配置完成文件、命令、流式动作和 resume；
5. 全量后端回归；
6. 明文密钥扫描。

## 6. G4 完成门禁

- Claude Adapter 实现统一 Port；
- 注册但非默认；
- G3 两个 P0 缺口有代码与测试证据；
- 当前环境真实 Adapter E2E 通过；
- OpenClaw 现有测试和平台全量回归不退化；
- 用户确认后才可进入 G5。

完成结果与证据见 `claude-agent-sdk-adapter-g4-result-2026-09-11.md`。截至 2026-09-11，以上门禁全部通过；默认 Runtime 仍为 OpenClaw。
