# Claude Runtime 生产路径 OpenClaw 残留分类（2026-09-12）

## 目的

本文件记录默认 Agent Runtime 切换后的生产代码残留扫描，避免把“仍能检索到 OpenClaw 文本”与“新 Run 仍由 OpenClaw 执行”混为一谈。最终门禁是：新建 Run 的执行链、部署依赖和新增事件不得依赖 OpenClaw；历史数据、对照基线和兼容读取可以保留，但必须分类且不得静默参与执行。

## 当前生产执行路径

- `server/app/agent_runtime_registry.py` 默认加载 `claude_code`；
- `server/app/platform_executor.py` 只通过通用 Runtime Port 调用当前 Adapter；
- `server/app/main.py` 新建 Agent、Run 启动和 Runtime Status 均使用 Registry 当前值；
- `compose.yaml` 与 `Dockerfile` 显式设置 `JIANGHU_AGENT_RUNTIME=claude_code`，镜像安装固定 Claude Agent SDK Bridge，不安装 OpenClaw 包；
- 数据库 Agent 默认值和旧 `runtime=openclaw` 记录启动迁移为 `claude_code`；
- 第 6 版真实 UI Run `run_d913ce06c52f` 的 `run.started`、`agent.runtime.ready`、工具、文件、命令、测试和恢复事件均记录 `claude_code` 或 `agent-sdk-bridge`；当前 Run 没有新增 `openclaw.*` 事件。

## 残留分类

### A. 历史 API 与事件读取兼容

- `/api/platform/openclaw/status`：旧客户端兼容别名；正式前端使用 `/api/platform/runtime/status`；
- `openclaw.runtime.*`、`openclaw.turn.*`：前端与状态推导仅用于读取历史 Run；新 Run 使用 `agent.runtime.*`、`agent.turn.*`；
- `openclaw_empty_output`：旧错误码的人类可读转换；不参与新 Runtime 调用。

这些项保持“只读兼容”，不得触发 OpenClaw 进程或写入新的 OpenClaw 事件。

### B. 迁移基线、对照脚本和合同测试

- `scripts/capture-openclaw-runtime-baseline.py`；
- G5 双 Adapter 对照脚本与结果汇总；
- `server/tests/runtime_contract/test_openclaw_runtime_contract.py`；
- Adapter parity 测试中的 OpenClaw 参数组；
- 历史 G1-G5 文档与实验结果。

这些内容用于证明迁移前能力和回归差异，不能作为生产启动依赖。删除它们会破坏可追溯基线，因此本轮保留。

### C. 基线专用 Legacy Adapter 源码（2026-09-13 已移出生产包）

- `server/app/openclaw_runtime.py` 已从生产包移除；
- 冻结实现迁移到 `experiments/openclaw_baseline/openclaw_runtime.py`，仅供迁移基线和 parity 测试显式导入；
- 生产 Registry 不再导入或注册 OpenClaw，也不再支持 `JIANGHU_ENABLE_LEGACY_OPENCLAW`；
- `JIANGHU_AGENT_RUNTIME` 只能是 `claude_code`，误配为 `openclaw` 或其他值时以 `agent_runtime_fixed_to_claude_code` 明确拒绝启动；
- 基线脚本和合同测试仍可直接构造 `OpenClawRuntime`，但该对象无法成为产品新 Run 的执行底座。

生产切换后的回滚只能使用上一版本发布物，不允许在当前版本内通过环境变量切回 OpenClaw。冻结源码继续保留在实验目录，避免丢失迁移前能力分母；生产残留扫描必须同时验证生产文件缺失、冻结文件位于实验目录。

### D. 命名清理项

- `client/src/style.css` 中 `.openclaw-runtime-card` 历史选择器已移除，当前 Runtime 卡片统一使用 `.runtime-status-card`；
- 部分旧设计/需求文档仍描述 OpenClaw 为当前默认 Runtime。

历史阶段文档不改写事实，但 `current-repository-architecture.md`、当前系统需求、ADR-0006、路线图和文档索引必须注明当前边界，防止读者把 G1-G5 的阶段描述误认为当前生产实现。

## 当前结论

代码扫描没有发现新 Run、前端正式 Runtime Status、Compose 或 Docker 仍依赖 OpenClaw 的证据。生产 Registry 已固定为 Claude Code SDK；当前 OpenClaw 残留只属于历史兼容读取、迁移基线/测试源码和待清理命名，不能参与新 Run。最终结论仍受第 7 版真实 UI E2E、RTC 全矩阵、全量测试、前端构建、凭据扫描和终态后迟到事件检查约束；这些门禁完成前不得宣称迁移验收通过。
