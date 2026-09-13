# Runtime 失败信息公开投影修复（2026-09-12）

## 问题现场

历史 Run `run_812706657344` 在模型网络连接失败后，把 OpenClaw/Provider 的完整内部日志直接写入公开事件。页面因此显示了 Runtime 启动阶段、工具策略、Memory 截断、Provider URL、Session 标识、`rawError`、lane 诊断和模型 fallback 细节。

原始失败的业务含义只是：模型服务请求在自动重试后仍无法建立网络连接。完整底层日志既不利于发起人理解，也会把内部地址、执行身份和安全策略下发到浏览器。

## 根因

1. 旧执行器把底层异常 `str(exc)` 直接放入 `agent.action.failed`、Task output 和后续重试上下文。
2. 前端的失败卡片、人物状态和江湖播报曾直接渲染事件 `summary` 或 `payload.error_detail`。
3. 新代码虽已为后续事件生成友好错误，但历史 Run 的原始证据仍在 SQLite；只做前端遮蔽时，Run 详情 API 依然会把原文发送到浏览器。

## 决策

- 原始失败证据继续保存在 SQLite，不覆盖、不迁移、不伪造成功，供受控诊断与历史审计使用。
- 所有新 Runtime 失败由 `public_runtime_error()` 分类为网络、鉴权、额度、限流、超时、配置、安全、无效输出或通用执行失败，只公开可行动说明、错误代码、可重试性和稳定 `diagnostic_id`。
- 所有浏览器可见 Run 快照增加服务端公开投影：移除 Session key/ID、SDK Session ID、writer/reader Session、原始 retry feedback 和 raw error；检测到 transport trace、Provider API URL、工具策略或内部启动日志时，用友好错误替换。
- 前端继续保留第二层兼容脱敏，以覆盖旧服务或缓存响应；“查看技术详情”改为“查看诊断摘要”。

## 修改范围

- `server/app/agent_runtime.py`：统一错误分类和公开错误结构。
- `server/app/platform_executor.py`：新失败、重试、Task 和 Run 事件只写公开错误。
- `server/app/main.py`：`public_platform_run()` 为历史与当前 Run API 生成服务端安全投影；启动、重试、取消、暂停、恢复、延时和介入响应均使用该投影。
- `client/src/App.vue`：失败记录、人物状态、世界播报和诊断摘要兼容处理历史原始日志。
- `server/tests/test_api.py`、`server/tests/runtime_contract/test_agent_runtime_port.py`：增加 URL、Session、工具策略和 transport trace 不得进入公开响应的回归测试。

## 验证证据

对真实历史 Run `run_812706657344` 读取数据库原始记录后执行服务端公开投影：

- 事件数：99；
- 公开响应不包含 `43.106.8.32`；
- 不包含 `sessionKey` / `session_key`；
- 不包含 `tools.profile`；
- 不包含 `provider-transport-fetch`；
- 包含友好网络错误说明；
- 生成 29 条诊断编号；
- SQLite 原始证据仍包含旧日志，证明公开投影没有改写历史。

回归结果：

- 公开投影定向测试：2 passed；
- Runtime Contract：62 passed；
- 后端全量：122 passed；
- 前端生产构建：通过，1777 modules；
- Python compile：通过；
- `git diff --check`：通过，仅有 Windows 行尾提示。

## 当前状态

运行中的真实 Claude SDK E2E Run 为 `run_9226059d74a1`。本修复不重启正在执行的后端，避免打断当前独立审计；待该 Run 到达安全边界后加载新服务端投影，并再次通过真实浏览器复验旧 Run。最终迁移结论仍以真实 `gate.passed` 与 `run.completed` 为硬门禁。
