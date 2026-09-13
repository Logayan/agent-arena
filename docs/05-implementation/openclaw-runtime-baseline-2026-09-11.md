# OpenClaw Runtime 能力基线报告（2026-09-11）

- 状态：部分冻结；GPT 单 Agent 文件与命令真实基线已通过，其余 P0 真实场景待冻结
- 阶段：Claude Code SDK 迁移 G1
- 基线源码：`ad7872ac913dcd62de28e811a41fcda3de595ac7`
- 约束：本报告不授权进入 G2，不授权接入 Claude Code SDK 或修改默认生产 Runtime

## 1. 结论

当前已冻结 OpenClaw 的静态配置、Runtime 合同、既有专项回归，以及使用最新 GPT 配置执行的单 Agent 文件与命令真实基线。最终严格基线中，`gpt-5.6-sol` 成功完成多轮模型调用、文件写入、PowerShell 命令执行、退出码采集和文件变更采集。G1 仍标记为“部分完成”，因为真实多 Agent、子 Agent、网络、MCP、故障恢复和 Docker 冷启动尚未全部冻结。

在获得一次可成功执行的受控真实基线前：

1. 不进入 G2，不实现 Claude Code SDK Adapter；
2. 不移除 OpenClaw，不切换默认路径；
3. 不把合同测试通过等同于真实能力通过；
4. 不重复请求已知余额不足的 `glm-5.1`；
5. 后续真实场景继续使用已确认的当前 GPT 配置，但不得无界重试；
6. 任何其他模型的真实调用必须先由用户确认费用和模型。

## 2. 环境指纹

| 项目 | 基线值 |
| --- | --- |
| Git HEAD | `ad7872ac913dcd62de28e811a41fcda3de595ac7` |
| OpenClaw | `2026.7.1-2 (0790d9f)` |
| Runtime Node | 仓库固定 `v24.15.0` |
| 系统 PATH Node | `v22.18.0`，不满足当前 OpenClaw 运行要求 |
| Python | 当前仓库 `.venv` |
| 操作系统 | Windows 10 x64 |
| 无费用基线 ID | `20260911T080314Z-ad7872ac913d` |
| GPT 真实探针 ID | `20260911T081218Z-ad7872ac913d` |
| GPT 严格通过基线 ID | `20260911T083751Z-ad7872ac913d` |

可复跑命令：

```powershell
.\.venv\Scripts\python.exe scripts\capture-openclaw-runtime-baseline.py
```

对应未提交运行证据位于：

```text
.data/verification/runtime-baselines/openclaw/20260911T080314Z-ad7872ac913d/manifest.json
```

`.data` 只保存本地运行证据，不作为需要提交的源文件。

## 3. 已通过的无费用基线

### 3.1 Runtime 合同测试

原始无费用 manifest 结果：`6 passed in 0.93s`。增加采集器和严格成功门禁回归后，最新真实基线中的 Runtime 合同结果为 `9 passed in 1.19s`。

合同测试覆盖：

- RTC-001 至 RTC-032 的编号、优先级和唯一性清单；
- Agent 身份、Persona、Memory、Skills 和同 Endpoint 多模型投影；
- 工程 Agent 与非工程 Agent 工具策略；
- Run 与 Agent Workspace 隔离；
- 公共工具动作提取、隐藏思维过滤和密钥脱敏；
- 工程提交、删除记录和完整 delivery 树晋升；
- 回合完成前的工具动作流式可见、文件变化和模型字段。
- active 数据库模型配置的只读加载与数据库不变性；
- Provider 401、余额不足和 Runtime 故障的分类。
- 真实基线必须存在成功 `exec`、退出码 0 且输出包含确定性标记。

测试源：

- `server/tests/runtime_contract/capability_cases.json`
- `server/tests/runtime_contract/test_openclaw_runtime_contract.py`

### 3.2 既有 OpenClaw 专项回归

结果：`5 passed in 4.11s`。

覆盖：Agent 修订后的 Workflow/Memory/知识连续性、逐节点模型覆盖、思维保护、隔离工程提交和工具动作实时流。

### 3.3 全量既有测试观察

此前同一 G1 工作中执行全量测试，结果为 `48 passed, 1 failed`。唯一失败为：

```text
test_platform_assets_are_persisted_and_workflow_binds_agents
```

该测试隐式依赖默认数据库中预先存在的 Workflow；使用独立临时数据库时列表为空。它不经过 OpenClaw Runtime，归类为已有测试隔离问题，不属于本次 Runtime 迁移导致的能力回退。修复该测试不在当前“只冻结 G1 基线”的授权内。

## 4. 真实探针结果与阻塞

真实探针运行目录：

```text
.data/verification/runtime-baselines/openclaw/20260911T075903Z-ad7872ac913d/
```

探针要求工程 Agent 在隔离的 `delivery` 目录创建确定性文件，并执行命令读取校验。实际结果：

- OpenClaw 正常启动并创建 Session；
- 请求使用 `anthropic-messages / glm-5.1` 到达模型网关；
- Provider 返回 HTTP 429，错误分类为余额或资源包不足；
- Token 用量为 0；
- 工具执行项为 0；
- 未创建目标交付文件；
- 失败发生在采集器增加异常归档逻辑之前，因此该目录没有完整 `manifest.json`，但保留了脱敏 Session 与 trajectory 证据。

结论：这是迁移前 Provider 计费阻塞，不是 OpenClaw 进程、配置投影或 Session 创建失败；同时它也不能证明真实工具能力成功。

## 5. 模型候选只读复核

本次只读取非敏感配置字段，没有读取或输出 Token，也没有发起模型请求。

| 来源 | Provider | 模型 | 层级/状态 | 结论 |
| --- | --- | --- | --- | --- |
| 环境变量 | `anthropic-compatible` | `glm-5.1` | 默认 Sonnet/Opus | 已知余额阻塞，不应自动重试 |
| 主数据库 | `openai-responses` | `gpt-5.6-sol` | medium，active | Endpoint 与 Token 已更新；严格单 Agent 文件＋命令基线通过 |

主数据库候选也验证了 ADR-0006 D-001 的必要性：Claude Code SDK 不能替代独立的 Native/OpenAI Agent Adapter。

### 5.1 当前 GPT 配置真实探针

运行命令：

```powershell
.\.venv\Scripts\python.exe scripts\capture-openclaw-runtime-baseline.py --real --real-model-source active-database
```

原始 manifest：

```text
.data/verification/runtime-baselines/openclaw/20260911T081218Z-ad7872ac913d/manifest.json
```

可观察序列：

1. OpenClaw 启动、模型解析和认证阶段完成；
2. 第一次 `POST /v1/responses` 返回 200；
3. 模型返回 `toolUse`，调用 `read`；
4. OpenClaw 执行 `read` 并产生 `toolResult`；
5. 第二次 `POST /v1/responses` 返回 401；
6. 回合以 `reason=auth` 结束，没有形成最终回答或目标交付文件。

这证明当前配置不是“完全无法请求”，但无法完成至少需要两次模型交互的工具闭环。基线分类应为 `provider_auth` 阻塞，不应归因于文件工具失败，也不能视为真实工程能力通过。原始 manifest 由旧分类逻辑写成 `runtime_failure/failed`；正式评估以本报告的复核结论为准，原始证据不改写。

对本机 OpenClaw `2026.7.1-2` 的只读源码检查显示，OpenAI Responses transport 会在每个模型回合重新创建 Client，并从同一 `options.apiKey` 构造请求；现有本地证据不能证明 OpenClaw 在第二轮主动丢弃了认证信息。要进一步区分“网关上游凭据轮转/过期”“自建网关对 function-call-output 续轮兼容问题”或“其他服务端鉴权规则”，需要查看 `43.106.8.32:3000` 对应网关的服务端日志。仅靠客户端再次付费重试不能可靠定位原因。

用户要求修改后，又执行了一次最小直接协议诊断：绕过 OpenClaw，从同一只读数据库配置加载 Token，使用相同 `Authorization: Bearer` 直接请求 `/v1/responses`，请求体只包含一个最小函数工具。该请求首轮即返回 401，未产生 Responses 事件或 function call。它与此前“首轮 200、续轮 401”合并说明当前网关认证状态不稳定或凭据已经失效；问题不再能通过调整 OpenClaw 的工具续轮消息格式解释。

仓库内已完成的修改是：

- 采集器支持从 active 数据库配置只读加载模型与本地解密 Token；
- 401、`reason=auth` 和同类错误统一归类为 `provider_auth/blocked`；
- 失败时归档已流出的公开工具动作，避免丢失“首轮是否已调用工具”的证据；
- 不对 401 自动重试，避免无效请求和额外费用。

该阶段无法仅靠仓库代码修复第三方凭据；随后用户提供了新的有效配置，阻塞已解除。原 401 记录继续作为 Provider 认证故障样本保留。

### 5.2 更新配置后的严格通过基线

用户提供新的 Base URL、模型和 API Key 后，配置被写入原 active 模型项。Token 通过隐藏输入传递，由平台现有 Fernet 机制加密保存；未写入命令行、代码或文档。随后发现第一次“passed”探针只成功创建文件，`exec` 因 `python -c` 触发 `strictInlineEval` 审批而失败。采集器原通过条件过宽，已修正为必须同时满足：

- 文件字节恰好为 `OPENCLAW_BASELINE_OK\n`；
- 存在 `exec` 工具结果；
- `is_error=false`、`status=completed`；
- `exit_code=0`；
- 命令输出包含 `OPENCLAW_BASELINE_OK`。

提示改为执行普通 PowerShell `Get-Content -Raw -LiteralPath .\openclaw-baseline.txt`，避免内联解释器审批路径。最终严格基线：

```text
.data/verification/runtime-baselines/openclaw/20260911T083751Z-ad7872ac913d/manifest.json
```

结果：

| 检查项 | 结果 |
| --- | --- |
| 总状态 | `passed` |
| Runtime 合同 | `9 passed` |
| 既有 OpenClaw 专项回归 | `5 passed` |
| Provider/模型 | `openai-responses / gpt-5.6-sol` |
| 文件内容 | 通过 |
| 文件 SHA-256 | `729226a116e1fcff90152ab99b90fa3902557a16e9eb5f28cf77554a21e3e923` |
| 命令执行 | `completed` |
| 命令退出码 | `0` |
| 命令输出 | `OPENCLAW_BASELINE_OK` |
| 流式公开动作 | 7 条 |
| 用量 | 输入 22,269 tokens；输出 576 tokens |

该结果正式冻结 RTC-006、RTC-007、RTC-010、RTC-012 和 RTC-026 的当前单 Agent 核心路径证据。此前 401 和错误通过记录保留为故障样本，不删除、不改写。

## 6. 必须区分的三类能力

### 6.1 OpenClaw 产品理论能力

OpenClaw 本体可提供子 Agent、Search/Fetch、渠道、定时任务、插件和更多工具。这些能力不能仅因 OpenClaw 安装包中存在就算作江湖 Online 当前能力。

### 6.2 当前项目实际启用能力

当前 `OpenClawRuntime.sync()` 明确配置：

- 工程 Agent：`coding` profile，只允许 `read`、`write`、`edit`、`apply_patch`、`exec`、`process`；
- 非工程 Agent：`minimal` profile；
- 本次真实轨迹记录工具数量为 6；
- 当前配置没有向该工程 Agent 开放 `sessions_spawn`、`subagents`、`web_search`、`web_fetch`、cron 或 goal 工具；
- 多 Agent 编排、Judge、返工、Artifact、Memory 写回和 Matrix 边界主要由江湖 Online 平台承担，不是由 Agent 自由调用 OpenClaw 工具完成。

因此，迁移时的“现状无回退”首先以当前实际启用能力和平台可观察行为为准。

### 6.3 已确认的目标能力

用户已确认：OpenClaw 能力由 Claude Code SDK、Adapter、平台服务或 MCP 等效替换，其他功能保持不变。由此，RTC-028 受控子 Agent、RTC-029 网络策略、RTC-030 Matrix 边界等即使当前不是直接暴露给 Agent 的 OpenClaw 工具，也仍属于迁移目标测试集，不能从计划中删除。

三类能力的关系是：

- 当前实际启用能力：迁移后必须 100% 保持；
- 已确认目标能力：必须按平台边界落地并验收；
- OpenClaw 理论但项目未启用、需求也未声明的能力：不自动纳入迁移范围。

## 7. RTC-001 至 RTC-032 的当前状态

能力清单已完整建立，但“清单存在”不代表“全部通过”。当前状态按层级归类如下：

| 状态 | 用例范围 | 说明 |
| --- | --- | --- |
| 已有合同或既有专项证据 | RTC-001～005、007～015、031 的部分或全部合同语义 | Fake/静态/文件级验证，不消耗模型费用 |
| 真实单 Agent 已通过 | RTC-006、007、010、012、026 的核心路径 | GPT 严格基线完成文件、成功 exec、退出码、流式动作和用量采集 |
| 仍需真实或平台专项基线 | RTC-016～030 | 多 Agent、通信、Judge、返工、Memory、暂停恢复、取消、重试、恢复、MCP、子 Agent、网络、Matrix |
| 仍需部署专项基线 | RTC-032 | Docker 干净环境冷启动尚未执行 |

后续必须给每个 RTC 增加明确的自动化测试映射和最近一次结果，避免仅有能力名称而没有证据。

## 8. G1 剩余门禁

G1 完成至少还需要：

1. 执行关键真实多 Agent、Judge/返工、取消/超时、恢复和权限安全场景；
2. 完成 Docker 冷启动基线；
3. 为 RTC-001 至 RTC-032 建立“测试文件/命令/结果/证据目录”映射；
4. 用户审阅最终 G1 差异和遗漏清单。

只有以上门禁满足后，迁移计划才能申请进入 G2。

## 9. 本次没有发生的变更

- 未修改 `server/app/openclaw_runtime.py` 等生产 Runtime 代码；
- 未安装或接入 Claude Code SDK；
- 未修改默认 Runtime、API、数据库语义、Matrix/Synapse 或前端行为；
- 仅按用户授权执行受控的 GPT 配置诊断与基线探针；
- 未再次调用已知余额不足的 `glm-5.1`。
