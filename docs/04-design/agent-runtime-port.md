# Agent Runtime Port 设计与 G2 实现记录

> 历史阶段说明：本文主体记录 2026-09-11 的 G2 状态。2026-09-12 生产切换后，Registry 已固定为 `claude_code`，实现位于 `claude_code_runtime.py` 与 `server/claude_agent_runtime/`；OpenClaw 只保留为基线测试源码，不能由产品 Registry 选择。当前架构以 `docs/architecture/current-repository-architecture.md` 为准。

- 状态：G2 已实现并通过本地回归
- 日期：2026-09-11
- 当前默认 Adapter：OpenClaw
- 范围：只完成框架解耦，不接入 Claude Code SDK，不切换生产路径

## 1. 目标

平台此前直接导入 `OpenClawRuntime` 和 `OpenClawRuntimeError`，使执行器、API 与具体底座耦合。G2 引入统一 Runtime Port，使平台只依赖稳定的模型回合、工具动作、工作区、提交与错误合同。OpenClaw 继续执行原有真实路径，后续 Claude Code SDK Adapter 必须实现同一 Port。

## 2. 代码结构

| 文件 | 职责 |
| --- | --- |
| `server/app/agent_runtime.py` | Port、公共 TypedDict、通用错误分类、确定性 Fake |
| `server/app/agent_runtime_registry.py` | Adapter 注册与当前默认 Adapter 选择 |
| `server/app/openclaw_runtime.py` | OpenClaw Adapter；保留原实现并实现统一 Port |
| `server/app/platform_executor.py` | 只依赖通用 Port 注册表和 `AgentRuntimeError` |
| `server/app/main.py` | 只依赖通用 Runtime 状态与同步入口 |
| `server/tests/runtime_contract/test_agent_runtime_port.py` | Port、Registry、Fake、错误和兼容路由测试 |

## 3. Port 合同

`AgentRuntimePort` 当前包含：

| 方法/属性 | 平台语义 |
| --- | --- |
| `runtime_name` | 稳定 Adapter 标识 |
| `supports_live_actions` | 是否支持回合结束前公开工具动作 |
| `for_run()` | 创建 Run 级状态和 Session 隔离边界 |
| `health()` | 返回统一健康状态，保留 Adapter 扩展字段 |
| `workspace_path()` | 返回指定 Agent 版本的隔离 Workspace |
| `sync()` | 投影身份、Memory、Skills、模型和工具政策 |
| `message()` | 执行受控模型回合并返回公共结果 |
| `publish_workspace_submission()` | 发布公开工程贡献，不泄露私有 Workspace |
| `promote_workspace_tree()` | 将完整正式交付树晋升到 Run code |

Port 继续使用平台已经消费的字典结构，避免 G2 同时引入大规模序列化迁移。公共类型只约束稳定字段，Adapter 可保留扩展字段。

## 4. 公共动作合同

公开动作限定为：

- `progress`：可公开的阶段或文本进度；
- `tool_call`：工具名、脱敏参数和调用 ID；
- `tool_result`：状态、错误标识、退出码和脱敏输出。

隐藏 thinking、内部 Prompt、Provider 密钥和 Adapter 私有事件不得进入该合同。OpenClaw 现有动作提取逻辑保持不变，Fake 可按相同结构确定性流式回放。

## 5. 公共错误合同

`AgentRuntimeError` 保存：

- `category`：稳定错误类别；
- `retryable`：Adapter 对是否可重试的建议；
- `runtime`：错误来源 Adapter；
- `details`：不含秘密的结构化扩展信息。

当前类别：

| 类别 | 典型情况 | 默认 retryable |
| --- | --- | --- |
| `configuration` | 缺模型、缺 Token、Runtime 不存在 | false |
| `provider_auth` | HTTP 401/403、认证拒绝 | false |
| `provider_billing` | 余额或资源包不足 | false |
| `provider_rate_limit` | HTTP 429 | true |
| `provider_failure` | 其他 Provider/LLM 失败 | true |
| `timeout` | 回合或子进程超时 | true |
| `cancelled` | 用户取消或外部中止 | false |
| `security` | 路径逃逸、权限拒绝 | false |
| `invalid_output` | 空输出、非 JSON 或结构不合法 | true |
| `runtime_failure` | 未归类 Runtime 故障 | true |

G2 只增加错误元数据，不改变平台现有自动重试次数和状态机；重试政策按类别收敛属于后续单独变更，防止本阶段改变产品行为。

## 6. Registry 与默认实现

`AgentRuntimeRegistry` 支持注册多个 Adapter，但当前只注册 OpenClaw 且保持默认：

```text
Agent Runtime Registry
└── openclaw (default)
```

没有配置开关可以在本阶段切换到 Claude。未知 Runtime 会明确返回 `agent_runtime_not_found/configuration`，不静默 fallback。

## 7. 兼容策略

- `OpenClawRuntimeError` 继承 `AgentRuntimeError`，原有捕获方和测试仍有效；
- `/api/platform/openclaw/status` 保留；新增等价 `/api/platform/runtime/status`；
- 原事件类型 `openclaw.runtime.ready/recovered` 和 `openclaw_sync` 字段暂时保留，避免破坏历史 Client 与数据；同时新增通用 `runtime_sync` 字段；
- 事件和 Task 输出中的 `runtime` 从 Adapter 动态取得，当前值仍为 `openclaw`；
- Registry 在没有 execution root 时只向旧测试 Stub 传 `run_id`，兼容既有轻量 Runtime；
- `prepare_openclaw_run` 暂保留为内部兼容别名，正式入口为 `prepare_agent_runtime_run`。

## 8. Fake Runtime

`FakeAgentRuntime` 用于无网络、无费用合同测试：

- 记录 `sync` 和 `message` 输入；
- 返回脚本化结果或异常；
- 按公共动作结构调用 `on_action`；
- 提供确定性 health、Workspace、提交和晋升接口；
- 不伪装真实模型效果，不作为生产 fallback。

## 9. 验证结果

执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

结果：`65 passed, 1 warning`。

迁移前无费用采集器复跑：Runtime 合同 `16 passed`，既有 OpenClaw 专项回归 `5 passed`，总状态 `passed`，基线 ID `20260911T091029Z-ad7872ac913d`。

Warning 来自现有 `openpyxl` 文件缺默认样式，与 Runtime Port 无关。

专项验证包括：

- OpenClaw 满足结构化 Port；
- OpenClaw 健康结果包含 `runtime=openclaw`；
- 通用错误分类和结构化输出；
- Fake 动作实时回放；
- Registry 默认 OpenClaw、可注册未来 Adapter、未知名称明确失败；
- 旧单参数 `for_run` Stub 兼容；
- API 和执行器不再直接导入 OpenClaw Adapter；
- 通用 Runtime 状态路由与旧 OpenClaw 路由共存；
- 原有团队合议、Judge 返工、恢复和重试测试继续通过。

## 10. G2 完成边界

G2 已满足：统一 Runtime Port、公共动作类型、错误分类、Fake、Registry，以及 OpenClaw 在不改变默认路径的情况下通过全量回归。

G2 不包含：

- Claude Code SDK 包或探针；
- Claude Adapter；
- 默认 Runtime 配置切换；
- 数据库 runtime migration；
- OpenClaw 事件和兼容字段删除；
- 按错误类别改变重试政策；
- OpenClaw 依赖移除。

以上内容必须按 G3-G7 的门禁另行授权。
