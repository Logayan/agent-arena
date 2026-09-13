# Claude Code SDK G3 技术探针结果

- 状态：当前 Windows 实际环境技术探针通过；不代表产品采用 Windows 优先策略
- 日期：2026-09-11
- SDK：`@anthropic-ai/claude-agent-sdk@0.3.268`
- 内置 Claude Code：`2.1.268`
- 当前生产 Runtime：仍为 OpenClaw
- 生产代码影响：无；没有注册 Claude Runtime、没有修改默认 Runtime、没有接入平台 API

## 1. 结论

Claude Agent SDK 可以使用用户当前保存的 GPT 配置完成真实 Agent 回合。虽然平台配置标签是 `openai-responses`，当前 Endpoint 同时通过了 Anthropic Messages `/v1/messages` 请求，并由 SDK 实际使用 `gpt-5.6-sol` 完成模型、工具、Session、MCP 和受控子 Agent 探针。

核心替换方向可行，但不能直接把 SDK 裸接到生产路径。G3 找到两个必须在 G4 修复的安全/生命周期缺口：

1. 取消 SDK Query 后，已启动的 Bash 子进程不会立即终止，会继续执行到自然结束并占用 Workspace；
2. SDK 内置 Bash 会继承 `ANTHROPIC_API_KEY`，工程命令可判断到 Provider 凭据存在。正式 Adapter 必须把模型认证与工具执行环境隔离。

Docker 客户端已安装，但本机 Docker daemon 未运行，因此本轮没有 Linux 镜像冷启动证据。当前任务实际运行于 Windows，SDK 路径已在当前环境完成真实验证。该结论不改变产品部署方向；Linux/容器证据应在实际使用相应环境时补充，见 ADR-0007。

## 2. 证据索引

机器可读总索引：`../../experiments/claude-agent-sdk-probe/results/g3-evidence-index.json`。

| 证据 | 内容 |
| --- | --- |
| `g3-probe-20260911T093016Z.json` | 当前 Endpoint 的 Anthropic Messages HTTP 200；首次 SDK 二进制因安装被中断而不完整，该次 SDK 失败不计为产品结论 |
| `g3-probe-20260911T093714Z.json` | 完整二进制校验后，最小 SDK Query 成功 |
| `g3-probe-20260911T094313Z.json` | Read/Write/Edit/Bash、CLAUDE.md、Skill、实时事件和 resume 成功；发现 Bash 凭据可见 |
| `g3-probe-20260911T094429Z.json` | 取消和进程回收失败证据 |
| `g3-probe-20260911T094755Z.json` | `canUseTool` 拒绝 Workspace 外路径，哨兵内容未泄露 |
| `g3-probe-20260911T095025Z.json` | MCP 工具与受控子 Agent 成功 |

所有 JSON 均不含 API Key。模型 Token 只由 Python 包装器从平台加密配置读取，通过子进程环境短暂注入；写结果前执行明文 Token 检测。

## 3. 探针明细

| 编号 | 状态 | 结果 |
| --- | --- | --- |
| P-001 SDK 包与 Node | 通过 | Node `v22.18.0` 可导入 SDK，SDK 要求 Node `>=18` |
| P-002 SDK/CLI 启动 | 通过 | 内置 Windows x64 二进制大小 `221,637,792`，SHA-256 与官方 manifest 一致，`--version` 返回 `2.1.268` |
| P-003 Endpoint 与认证 | 通过 | 当前 Endpoint 的 `/v1/messages` 返回 HTTP 200；SDK 认证源为 `ANTHROPIC_API_KEY` |
| P-004 指定模型 | 通过 | SDK init 明确返回 `gpt-5.6-sol` |
| P-005 Session/resume | 通过 | Session ID 存在，resume 使用相同 ID 并准确回忆前一回合 nonce |
| P-006 文件与命令工具 | 通过 | Read、Write、Edit、Bash 各有真实 tool call/result；输出文件内容精确匹配 |
| P-007 CLAUDE.md/Skills | 通过 | `CLAUDE_MD_OK` 与 `SKILL_OK` 均进入文件和最终回复 |
| P-008 实时事件 | 通过 | 功能回合共 313 个事件、10 个工具事件，tool result 在 terminal result 前到达 |
| P-009 取消/超时 | 未通过 | Abort 后 12 秒 Bash 仍自然跑完，总耗时约 13.2 秒；Workspace handle 未及时释放 |
| P-010 Docker Linux | 当前路径不适用 | 当前运行环境为 Windows，已验证路径不依赖 Docker；Docker daemon 不可用事实保留，待实际进行 Linux/容器部署时验证 |
| P-011 数据与网络 | 有条件 | 使用独立临时 `CLAUDE_CONFIG_DIR`，关闭非必要流量和 Prompt suggestion；SDK README 声明会收集部分 usage/feedback，生产需网络策略与条款复核 |
| P-012 安全边界 | 部分通过 | `canUseTool` 成功拒绝 Workspace 外 Read；但 Bash 可见模型凭据环境变量 |
| P-013 MCP | 通过 | 同进程 MCP marker 工具注册并调用一次，结果可观察 |
| P-014 受控子 Agent | 通过 | 只允许一个命名子 Agent，无工具、单轮、指定模型；成功返回确定性 marker |

## 4. 当前 GPT 配置结论

对用户当前配置的结论是“可用于 Claude Agent SDK”，不是“所有 OpenAI Responses Endpoint 都天然兼容 Claude SDK”。当前网关同时支持 Anthropic Messages，因此 Adapter 可以把同一已加密 Token 映射为 SDK 进程环境，并显式指定 `gpt-5.6-sol`。

ADR-0006 D-001 仍然成立：平台需保留 Native/OpenAI Agent Adapter，给只支持 OpenAI Responses 的其他模型配置使用；Runtime 路由必须依据实际协议能力，不能只看 Provider 标签或把失败静默 fallback。

## 5. G4 必须实现的补齐项

1. **进程树监管**：Windows 使用 Job Object 或等效树终止；Linux 使用进程组/cgroup。取消与超时必须杀掉 Bash、PowerShell、子 Agent 和 MCP 派生进程，并验证 Workspace 可立即释放。
2. **凭据隔离**：模型 Token 只能到 SDK/CLI 请求层，不能继承给 Bash。优先把命令执行重定向到平台 MCP Tool Gateway；若使用内置 Bash，需可信 launcher 做环境白名单和凭据剥离。
3. **Workspace 强制边界**：所有 Read/Write/Edit/Bash/MCP 调用通过 `canUseTool` 或平台工具网关做规范化路径判断，不依赖 `cwd` 自身作为沙箱。
4. **协议探测与路由**：新增配置能力字段或受控探测，明确 `anthropic-messages` 与 `openai-responses`；当前双协议网关可走 Claude Adapter，其他配置按能力走 Native/OpenAI Adapter。
5. **事件归一化**：把 assistant `tool_use`、user `tool_result`、result、permission denial 和 subagent parent ID 映射到现有 Runtime Action 合同，隐藏 thinking 和凭据。
6. **Session 映射**：平台持久化 Session ID；`CLAUDE_CONFIG_DIR` 位于平台数据目录的 Run/Agent 隔离分区，resume 不读取其他 Agent 数据。
7. **环境对应验证**：Adapter 保持跨平台设计。进行 Linux/容器部署时运行独立 `experiments/claude-agent-sdk-probe/Dockerfile`，验证 Linux x64 二进制、非 root、冷启动时间和退出回收。

## 6. 验证

- 所有 `src/*.mjs`：`node --check` 通过；
- 探针 Python 包装器：`py_compile` 通过；
- 独立探针依赖：`npm ls --depth=0` 通过，只包含固定 SDK `0.3.268`；
- 全量后端：`65 passed, 1 warning`；
- Warning 为既有 openpyxl 默认样式提示，与迁移无关；
- 根目录 `npm ls` 的 extraneous/invalid 输出来自既有手工 OpenClaw 安装树，独立探针目录不受影响。

## 7. 门禁

当前 Windows 环境技术可行性已经成立，G3 完成。该结论只是按当前实际环境验证，不代表 Windows 优先。进入 G4 仍需用户明确授权，且 G4 必须先解决进程树回收和凭据隔离。

补充尝试：收到用户再次“继续”后，已尝试隐藏启动 `Docker Desktop.exe` 和启动 `com.docker.service`。前者被管理员策略限制，后者因当前进程无服务启动权限失败。该事实作为环境证据归档，不再错误地作为当前 Windows SDK 路径的失败条件。
