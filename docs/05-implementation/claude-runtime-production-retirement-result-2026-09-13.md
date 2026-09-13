# Claude Code SDK 生产切换与 OpenClaw 退役整改记录（2026-09-13）

## 1. 范围与当前结论

- 目标：江湖 Online 的生产 Agent Runtime 仅允许 Claude Code SDK，旧 OpenClaw 实现不得留在 `server.app` 或被生产入口导入、注册、部署、故障转移。
- 不变项：历史 Run 的 `openclaw.*` 事件仍可读；`/api/platform/openclaw/status` 仍作为只读兼容别名；历史能力基线和 parity corpus 不删除。
- 当前代码结论：生产源码残留整改与本地工程回归通过。
- 总体验收结论：**仍未封版**。只有 `run_bda13e93b2ea` / Version 9 获得最终独立 Judge `ACCEPT`、Gate 通过并进入 `run.completed` 后，才能宣告整体迁移完成。

## 2. 代码决策

1. 将 `server/app/openclaw_runtime.py` 移至 `experiments/openclaw_baseline/openclaw_runtime.py`。
2. 旧类名、协议文本和直接 parity 能力保持不变，只调整其包边界与导入路径。
3. `AgentRuntimeRegistry` 仍只构造 `claude_code_runtime`；非 `claude_code` 配置继续 fail-closed。
4. Runtime Source Attestation 新增两项硬检查：
   - 生产包内 OpenClaw Adapter 文件必须不存在；
   - 冻结基线必须位于实验目录。
5. 删除前端已无引用的 `.openclaw-runtime-card` CSS；当前卡片统一使用 `.runtime-status-card`。
6. 项目元数据从 `openclaw-claude-sdk-acceptance` 改为 `jianghu-claude-code-sdk-acceptance`。
7. 依赖大型外部冻结快照的两组根目录测试，在夹具未物化时明确 `SKIP`，不再以加载异常冒充产品测试失败，也不把 SKIP 计为验收 PASS。

## 3. 真实前端 E2E 证据

同一 Run、同一 Version、真实前端 `127.0.0.1:5173`、真实后端 `127.0.0.1:8003`：

```text
command=npx playwright test --config=playwright.final-v5.config.mjs
tests=11
passed=11
failed=0
skipped=0
exit_code=0
logged_rerun_duration=3.6m
screenshots=15
screenshot_bytes=52,706,421
junit_tests=11
junit_failures=0
json_expected=11
json_unexpected=0
```

覆盖场景包括：真实端点健康、组织/委托首页、进入既有 Run 且不新建、团队与流程图、执行进度、Claude Runtime 状态、Tool 事件、Artifact 查看与下载 SHA-256 复算、失败历史与恢复后版本、Judge 等待门禁、当前协作卷宗。

Trace 说明：v5 配置为 `trace: retain-on-failure`，本轮 11 项全部通过，因此成功复跑没有生成失败 Trace；15 张逐场景截图、JUnit、JSON 原始结果、HTML 报告、浏览器 console/network 观察与下载回执均已生成。历史失败 Attempt 的 Trace 保持不覆盖。

## 4. 工程回归

```text
生产残留定向测试：63 passed
后端全量测试：178 passed, 1 third-party warning
Claude SDK Bridge：8 passed
前端生产构建：PASS（1777 modules transformed）
根目录历史证据复算：0 executed, 2 skipped
  - evidence/platform_snapshot/events.ndjson 未物化
  - evidence/runtime_probe/platform_snapshot/README.md 未物化
```

两个 SKIP 仅代表仓库未携带大型外部冻结夹具，不用于证明迁移通过。当前 Run 内的实时 Artifact Registry、浏览器证据和独立 Judge 仍需按平台流程完成登记、下载复算和裁决。

在恢复 epoch Attempt 血缘修复提交后再次执行同一工程门禁，结果保持为后端 `178 passed, 1 third-party warning`、Claude SDK Bridge `8/8 passed`、前端生产构建 `1777 modules transformed`。该回归使用测试环境，不修改 `run_bda13e93b2ea` 的事件或 Artifact；实时 Run 的最终裁决仍以平台内注册证据和独立 Judge 为准。

凭据扫描 `scripts/check-no-secrets.ps1` 返回 `secret_scan=passed`；生产 Runtime Port 与 source-attestation 定向合同 `44 passed, 1 third-party warning`。扫描结果只证明仓库提交内容未发现密钥落盘，不输出或归档实际凭据值。

## 5. 生产残留扫描

本地严格扫描结果：

```text
production_adapter_absent=true
baseline_adapter_present=true
runtime_registry_claude_only=true
project_name=jianghu-claude-code-sdk-acceptance
production_execution_violation_count=0
```

`_runtime_source_attestation(agent_runtime.health())`：

```text
status=passed
checks=11/11
blocking_findings=0
runtime=claude_code
mode=agent-sdk-bridge
```

允许保留的 OpenClaw 文本范围：历史文档、冻结实验基线、迁移对照测试、旧事件显示映射和兼容状态 API。它们不得构造旧 Runtime、产生新 OpenClaw 事件或成为故障回退路径。

## 6. 未完成门禁

- `final_report_and_gap_list` 仍在执行与自动恢复；
- 新 v5 封版文件仍需由平台逐项注册、采集并下载复算；
- `final_independent_judgement` 尚未完成；
- `gate.passed` / `gate.accepted` 与 `run.completed` 尚未出现；
- 服务应在当前活跃 Run 到达安全边界后重启，以加载最新 Python Runtime 代码，再执行一次终态回归。

本文件是工程现场记录，不替代独立 Judge 裁决。
