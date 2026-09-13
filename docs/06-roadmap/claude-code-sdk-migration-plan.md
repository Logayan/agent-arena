# Claude Code SDK Agent Runtime 迁移计划

- 状态：G1-G6 已执行，G7 收尾与真实 UI E2E 最终裁决进行中；尚未达到 `gate.passed + run.completed`
- 日期：2026-09-11
- 目标：在可证明能力不回退的前提下，将默认 Agent 底座从 OpenClaw 完整迁移到 Claude Code SDK
- 授权状态：用户已确认完整替换范围并授权代码修改、真实前端端到端执行与收尾验证

## 1. 目标边界

完成后：

- 新建 Run 的默认 Agent 执行路径不再依赖 OpenClaw。
- Claude Code SDK 承接受控 Agent 回合的模型与工具循环。
- 平台继续负责多 Agent 编排、权限、Memory、知识、事件、Artifact、Judge、返工、暂停、恢复和审计。
- OpenClaw 包、Docker 层、环境变量、健康接口和新运行路径被移除。
- 历史 OpenClaw 数据和事件保持可读。
- Matrix、调度、多渠道及其他非 OpenClaw 产品能力保持不变。
- OpenClaw 原先承担但 Claude SDK 不原生提供的能力，由 Adapter、平台服务或 MCP 等效补齐，不因迁移被删除。

本次不把 Claude SDK Session 变成平台 Workflow，不以模型自述替代真实文件和测试，不用静默 fallback 掩盖失败。

## 2. 阶段与门禁

### G0：目标和决策冻结

交付：ADR-0006 的 D-001 至 D-007。

通过条件：用户确认模型兼容、Matrix、权限、子 Agent、Session 生命周期、数据政策和回滚方案。

当前进度：D-001 至 D-007 已收敛；G1 核心基线、G2 Runtime Port、G3 技术探针和 G4 非默认 Claude Adapter 均已完成。当前停在 G5 授权门禁。

### G1：OpenClaw 能力基线冻结

交付：Runtime 合同、测试集、真实 E2E 报告、脱敏 fixtures 和基线 manifest。

通过条件：当前 OpenClaw P0 能力已被测试覆盖，真实测试可复跑，费用和版本记录完整。

当前进度（2026-09-11）：部分完成。RTC-001 至 RTC-032 能力清单、9 个 Runtime 合同测试、5 个既有 OpenClaw 专项回归和无费用 manifest 已完成。用户更新当前 `openai-responses / gpt-5.6-sol` 配置后，严格单 Agent 基线已完成文件写入、普通 PowerShell 命令、退出码 0、流式动作、文件哈希和用量采集。真实多 Agent、故障/安全和 Docker 冷启动仍待冻结。详见 `../05-implementation/openclaw-runtime-baseline-2026-09-11.md`。

当前门禁：真实单 Agent 核心路径已冻结。用户已明确授权并完成 G2；真实多 Agent、故障/安全和 Docker 冷启动等剩余证据继续作为 G5/G6 前不可跳过的回归门禁。

### G2：统一 Agent Runtime Port

交付：框架无关的 Runtime 接口、事件 Schema、错误分类和测试 Fake。

通过条件：现有 OpenClaw Adapter 在不改变实际行为的情况下通过新合同测试。

当前进度（2026-09-11）：已完成。新增框架无关 Port、公共动作与错误类型、Registry 和确定性 Fake；平台 API 与执行器不再直接导入 OpenClaw Adapter。OpenClaw 仍是唯一默认实现，旧状态路由和事件兼容字段保留。全量后端回归 `65 passed, 1 warning`。详见 `../04-design/agent-runtime-port.md`。

阶段边界：未接入 Claude Code SDK，未切换默认 Runtime。进入 G3 前必须再次获得用户授权。

### G3：Claude Code SDK 技术探针

交付：独立实验目录中的 SDK 探针结果，不接入生产 API。

验证：

- 自定义 Endpoint 和认证；
- 指定模型；
- Session 创建与 resume；
- Read/Write/Edit/Bash；
- Skills 与 `CLAUDE.md`；
- tool_use/tool_result 实时流；
- 取消、超时和子进程回收；
- Docker Linux 冷启动；
- SDK 数据与网络行为。

通过条件：不存在阻断性缺口；缺口已有平台或 MCP 补齐方案。

当前进度（2026-09-11）：用户已明确授权进入 G3。只允许在独立实验目录运行 SDK 探针，不注册 Claude Runtime、不修改默认 Runtime、不接入生产 API。计划与判定标准见 `../05-implementation/claude-code-sdk-technical-probe-plan-2026-09-11.md`。

探针结论（2026-09-11）：当前 GPT Endpoint、`gpt-5.6-sol`、Session/resume、Read/Write/Edit/Bash、CLAUDE.md、Skill、实时事件、MCP、受控子 Agent 和 Workspace 权限回调已在当前 Windows 环境验证。发现取消不回收 Bash 后代、Bash 可见模型凭据两个必须在 G4 补齐的缺口。测试按当前实际环境执行，不代表产品采用 Windows 优先策略；其他部署环境在实际使用时分别验证，见 ADR-0007。

### G4：Claude Code SDK Adapter 实现

交付：

- Run/Agent Workspace；
- 身份、Memory、Skills 投影；
- Session 映射；
- 工具与权限；
- 实时动作归一化；
- 文件变更和工程提交；
- 用量、错误、取消和恢复；
- 子 Agent 政策。

通过条件：L1 合同测试全部通过，不改变默认生产 Runtime。

当前进度（2026-09-11）：已完成。Claude Adapter、MCP Workspace Gateway、Session、流式动作、文件提交、错误和进程树监管均已实现；当前加密 GPT 配置真实 E2E 的 15 项检查全部通过，全量后端为 `71 passed, 1 warning`。Adapter 已注册但默认仍为 OpenClaw。详见 `../05-implementation/claude-agent-sdk-adapter-g4-result-2026-09-11.md`。

阶段边界：未执行 OpenClaw/Claude 同题完整差异验证，未切换默认 Runtime。进入 G5 前必须再次获得用户授权。

### G5：同题能力对照

交付：OpenClaw 与 Claude Code SDK 的同一测试集差异报告。

通过条件：P0 能力无回退；安全门禁通过；性能和成本差异经确认。

当前进度（2026-09-11）：用户已明确授权进入 G5。计划见 `../05-implementation/openclaw-claude-runtime-g5-comparison-plan-2026-09-11.md`。G5 只运行双 Adapter 对照和形成差异报告，不切换默认 Runtime。

### G6：生产路径切换

交付：

- 默认 Runtime 和 API 切换；
- 数据库 migration；
- 前端状态、文案和设置；
- Docker 和 Compose；
- 新真实 E2E 脚本；
- 监控和故障说明。

通过条件：完整单测、前端构建、Docker 构建、真实 E2E 和恢复测试通过。

当前进度（2026-09-12）：代码与本地运行路径已切换。生产 Registry 固定 `claude_code`，Claude Agent SDK Bridge 已承载真实多人 Run；后端全量 `105 passed`、Runtime 合同 `50 passed`、Bridge `6/6`、前端 1777 模块生产构建通过。Docker 不是当前 Windows 验证环境的运行前置条件，镜像配置已移除 OpenClaw 安装。真实 UI E2E 第 7 版已从首轮预期退回进入 `remediation_rerun`，但最终 Judge 尚未通过，因此 G6 仍标记为“实现完成、终态验收中”。

### G7：OpenClaw 移除与收尾

交付：

- 删除 OpenClaw 包与运行代码；
- 删除只服务于 OpenClaw 的环境变量和镜像层；
- 保留历史读取兼容；
- 更新需求、设计、ADR、README 和运维文档；
- 最终迁移报告。

通过条件：仓库运行代码和部署配置不再引用 OpenClaw；历史文档和历史事件可保留其事实记录。

当前进度（2026-09-12）：产品 Registry 已不导入、不注册 OpenClaw，旧环境开关已删除，误配旧 Runtime 会明确拒绝启动；OpenClaw 源码仅保留给迁移基线和合同对照直接实例化，无法承载产品新 Run。当前架构、ADR、残留分类和执行日志已更新。剩余门禁是第 7 版真实整改、最终报告、最终 `gate.passed`、`run.completed`、终态机器汇总及迟到事件稳定窗口。

## 3. 预期影响文件

### Runtime 与执行器

- `server/app/openclaw_runtime.py`
- 新统一 Runtime Port 与 Claude Adapter
- `server/app/platform_executor.py`
- `server/app/main.py`
- `server/app/platform_store.py`

### API 与 Client

- Runtime status API
- Agent runtime 字段和校验
- `client/src/api.ts`
- `client/src/App.vue`
- Runtime、模型和错误文案

### 构建与部署

- `Dockerfile`
- `compose.yaml`
- `.env.docker.example`
- `package.json`、`package-lock.json`
- SDK 版本固定和多架构安装

### 测试与脚本

- `server/tests/test_api.py`
- 新 Runtime 合同测试集
- `scripts/verify-real-openclaw-e2e.py`
- 新 Claude Code SDK E2E、故障和安全脚本

### 文档与数据

- ADR-0005/0006
- 当前架构图和 Runtime 设计
- 系统需求中的 OpenClaw 专用条目
- 数据库 runtime 默认值和历史兼容说明
- Matrix Bridge 与调度设计

## 4. 数据迁移原则

- 新 Agent 默认 runtime 使用新的枚举值。
- 已存在且尚未执行的 OpenClaw 配置需显示迁移状态，不静默改写。
- 历史 Run、Artifact、事件和外部 Session ID 原样保留。
- 新旧事件通过 Runtime 类型区分，查询层提供统一公共视图。
- 数据 migration 必须可重复、可检测并有备份说明。

## 5. 发布与回滚

- 非生产环境允许同题双跑，结果不能互相覆盖。
- 生产切换使用新版本镜像，切换前冻结数据库备份和基线报告。
- 应用内部不自动从 Claude 回退到 OpenClaw。
- 如出现阻断问题，人工回滚到上一完整镜像和对应配置；回滚后保留失败 Run 证据。
- OpenClaw 依赖仅在新版本验收通过后从主分支删除。

## 6. 完成定义

只有全部满足才算“完整切换”：

1. 默认 Agent Run 不启动 OpenClaw 进程。
2. Docker 镜像不安装 OpenClaw。
3. 新 Runtime 通过统一测试集和真实 E2E。
4. 身份、Memory、Skills、Session、工具、文件、子 Agent 和实时动作有明确实现。
5. 多 Agent、Judge、返工、暂停、恢复、取消和预算无回退。
6. Matrix、调度和外部写操作有明确替代方案。
7. OpenAI Responses 等模型兼容策略已经落地。
8. 历史数据可读且未被伪造改写。
9. 安全、隐私、许可证和成本结论有文件记录。
10. 用户批准最终能力差异报告。
