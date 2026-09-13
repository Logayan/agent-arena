# Claude Code SDK G3 独立技术探针计划

- 状态：当前 Windows 环境技术探针已完成；其他部署环境在实际使用时分别验证
- 日期：2026-09-11
- 阶段：G3（独立技术探针）
- 生产影响：无；不注册 Claude Runtime，不修改默认 Runtime，不接入平台 API
- 凭据原则：只在探针进程内从平台加密配置读取，不写入源码、命令输出、报告或 fixture

## 1. 本阶段目标

在实现 Claude Runtime Adapter 前，以独立实验验证 Claude Code SDK（现包名 `@anthropic-ai/claude-agent-sdk`）的真实接口、运行依赖和协议边界，并判断当前平台模型配置能否直接使用。

本阶段只回答“SDK 是否可用、缺口在哪里、下一阶段该如何实现”，不改变江湖 Online 的任何生产执行行为。

## 2. 固定输入

- SDK：`@anthropic-ai/claude-agent-sdk`，安装时固定精确版本并记录 lockfile。
- 当前模型配置：从 `.data/jianghu.db` 经现有 `PlatformStore` 和 Fernet 密钥读取。
- 当前已知配置协议：`openai-responses`。
- 当前模型：只在脱敏报告中记录模型名；Token 不落盘、不输出。
- 工作区：独立临时目录，不读取或修改真实 Agent Workspace。

## 3. 探针项与判定

| 编号 | 探针 | 通过条件 | 失败时结论 |
| --- | --- | --- | --- |
| P-001 | SDK 包与 Node 兼容 | 可导入、版本与 Node 要求可记录 | 阻断 G4，先解决运行依赖 |
| P-002 | SDK/CLI 启动 | 独立 Query 可启动并产生结构化事件 | 阻断 G4 |
| P-003 | 当前 Endpoint 与认证 | 当前加密配置可完成最小请求，或明确识别协议不兼容 | 协议不兼容时转 Native/OpenAI Adapter，不伪装成功 |
| P-004 | 指定模型 | 请求实际使用指定模型或明确返回不支持 | 形成模型路由缺口 |
| P-005 | Session 与 resume | 首回合获得 Session ID，第二回合可恢复上下文 | 由 Adapter 补持久映射或判定阻断 |
| P-006 | Read/Write/Edit/Bash | 在隔离目录产生可核验文件和命令结果 | 形成工具映射缺口 |
| P-007 | `CLAUDE.md` 与 Skills | 指令可被发现且有可观察证据 | 由投影层或 MCP 补齐 |
| P-008 | 实时工具事件 | 可区分 tool call/result，并记录顺序与 ID | 由事件归一化层补齐 |
| P-009 | 取消与超时 | 可中止，子进程不残留，迟到结果不晋升 | 阻断 G4 或增加进程监管层 |
| P-010 | Docker Linux 冷启动 | 固定镜像可安装、导入、启动探针 | 形成部署阻断或镜像方案 |
| P-011 | 数据与网络行为 | 环境变量、持久目录和外部请求边界可说明 | 不明数据外发则阻断生产切换 |
| P-012 | 安全边界 | 探针不能越出隔离 Workspace，日志不含 Token | 泄密或路径逃逸则阻断 G4 |
| P-013 | MCP 工具 | 受控 MCP 工具可注册、授权、调用并产生事件 | 由平台 Tool Gateway 补齐 |
| P-014 | 受控子 Agent | 仅允许的子 Agent 可被调用，模型、工具和轮次受限 | 阻断子 Agent 能力迁移 |

## 4. 执行顺序

1. 创建 `experiments/claude-agent-sdk-probe/`，只放独立 Node 探针、精确依赖和说明。
2. 先运行无凭据静态探针：导入、版本、导出 API、CLI 路径、消息类型。
3. 使用当前平台配置分别做协议预检和最小 SDK Query；所有输出经过字段白名单与脱敏。
4. 仅在 Endpoint/认证可工作时继续 Session、工具、实时事件和取消探针，避免无意义费用。
5. 本机探针稳定后再做 Docker 冷启动；不改当前生产 Dockerfile/Compose。
6. 生成机器可读 JSON 结果和人工结论报告，更新路线图与日志，然后停在 G3 门禁。

## 5. 安全与费用控制

- 默认最小轮次、短 Prompt、低 `maxTurns`，不并发压测。
- 报告只保留状态码、错误类别、SDK 事件类型、耗时、用量和内容哈希；Provider 原始错误正文先脱敏再截断。
- 子进程环境仅注入本次需要的变量；不继承无关秘密。
- 临时工作区可删除，正式探针代码和脱敏结果保留用于复跑。
- 当前配置若仅支持 OpenAI Responses，则 P-003 记录为“Claude SDK 协议不兼容”，后续由已确认的 Native/OpenAI Agent Adapter 承接，不修改用户配置来绕过结论。

## 6. G3 完成门禁

G3 只有在以下内容全部归档后才完成：

1. SDK 精确版本、Node/OS/Docker 环境；
2. P-001 至 P-014 的状态、证据位置和缺口归属；
3. 当前 GPT Endpoint 能否被 Claude SDK 直接使用的明确结论；
4. 进入 G4 前必须实现的 Adapter/MCP/平台补齐项；
5. 不含明文凭据的复跑命令和结果；
6. 用户确认是否进入 G4。
