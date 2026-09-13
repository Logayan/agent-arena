# Claude Agent SDK Runtime 取证与故障注入验收报告

**Run：** `run_9226059d74a1`  
**节点：** Runtime 取证与故障注入执行环境  
**工程实现者：** 林砚｜后端工程师｜`agent_eac0b56ad320`  
**发起人现场补充意见：** 无；本轮未扩展或缩减验收范围。  
**证据截止：** platform metadata `2026-09-12T08:05:47.692752+00:00`；公开投影 sequence `1..6015`。

## 一、正式结论【决定】

```text
runtime_probe_engineering_delivery=PASS
platform_projection_integrity=PASS_PUBLIC_AGENT_SAFE_SCOPE
platform_registered_artifact_bytes=PASS_38_OF_38
local_fault_injection=PASS_LOCAL_SCOPE
predeclared_candidate_v1_gate=REJECT_EXPECTED_EXIT_42
cam_pass_count=0_OF_13
claude_agent_sdk_full_runtime_migration=NO_GO
openclaw_retirement=REJECTED
```

本节点交付的是可运行采集器、证据索引、隔离故障探针和失败关闭门禁。工程与本地探针通过，不等于平台全 Runtime 迁移通过。当前冻结投影仍缺五角色全链路、独立 Judge、平台 intentional pause/resume、Memory 同值跨新 Session 读用闭环、终态对账及 OpenClaw 零流量证据。

## 二、事实与平台证据【事实/证据】

### 2.1 投影完整性

- 实际读取：`.jianghu-platform-evidence/events.ndjson`，冻结到 `evidence/runtime_probe/platform_snapshot/events.ndjson`；
- 字节数：`14040589`；SHA-256：`41171e25f262f44f71aad2273dbac20c556bd807ca95c8ac1ff036aef38ebc40`；
- 投影事件：`6003`；metadata event count：`6015`；sequence `1..6015`；过滤缺口：`[687, 812, 1258, 2248, 3898, 3937, 4211, 4329, 4980, 5167, 5676, 5824]`；
- sequence、event ID、source_event_sha256 均唯一；critical event `616` 条逐对象与投影一致；
- 边界：这是 `public_agent_safe` 投影，不是源数据库导出，未读取或注入发起人私享审计内容。

### 2.2 Runtime 与 SDK Session

- Runtime health：`claude_code` / `agent-sdk-bridge`；Bridge `0.3.268`；Claude Code `2.1.268`；
- source attestation：`passed`，源码指纹 `13` 项；
- route attestation：seq 4 / `evt_4a4797263797`, seq 2522 / `evt_c72cdb538df1`；
- completed-turn SDK binding：`26/26` 逐 sequence、event ID、source hash、platform Session 与 SDK Session 一致；
- distinct bound actor：`5`；distinct SDK Session：`26`；
- 限制：`agent.turn.started` 不携带 SDK Session ID，显式 `sdk.session.started`=0、`sdk.session.continued`=0。attestation 中 `model` 字段不被解释为模型供应商端到端执行证明。

### 2.3 Tool 请求、结果和副作用

- Tool group：`979`；授权/started/completed/side-effect 四阶段完整：`979`；不完整：`0`；
- completion：`{'completed': 903, 'failed': 76}`；authorization：`{'allow': 979}`；side effect：`{'completed': 903, 'failed_preserved': 76}`；
- 失败清单：`evidence/runtime_probe/failed-tool-inventory.json`；
- 限制：投影未提供原始 Tool Request/Result 字节、独立参数 Schema 判定、SDK invocation ID、result digest/output SHA-256，因此只能判 `PARTIAL`。

### 2.4 文件与 Artifact Registry

- 文件事件：created `269`、modified `94`、deleted `38`；
- Registry：`38` 项，SHA-256 `fcb672952ddae343fd87a69da6aef9ee54f5893445ffb85782d75ef2e418ac44`；
- 原始物化字节、expected/observed SHA-256、大小、source event sequence/id/hash：`38/38` 全部一致；
- `artifact.collected` / `artifact.download.verified`：`36` / `36`；两份 workflow output 没有同等完整的 collect/download 事件，因此 CAM-04 保持 `PARTIAL`；
- 逐项收据：`evidence/runtime_probe/platform_snapshot/artifact-byte-receipts.json`（共 `38` 项）。

### 2.5 公开协作、Judge、返工与 Memory

- `agent.message.sent`：`14` 条，覆盖 `5` 个发送 actor；该计数没有绑定产品、架构、工程、质量和独立裁判五个要求角色，不能据此判定五角色生产流通过；
- Judge/gate 事件：`0`；不得把本地预门禁冒充独立 Judge；
- `attempt.created`：`6`，其中 `rework_of` 非空 `1`；存在返工 Attempt 事实，但没有 Judge 因果链；
- Memory candidate/review/commit/persist：`4/4/4/2`；commit 锚点：seq 5019 / `evt_2d4680c2339f`, seq 5022 / `evt_c1d0f6601289`, seq 5328 / `evt_c1ba6d8382c1`, seq 5331 / `evt_3e9f4a625669`；
- retrieved/used：`232/208`；本轮 commit 后同值跨新 Session retrieve/use：`False`。

### 2.6 暂停与恢复

- intentional platform pause/resume 事件：`0`；
- 后端中断恢复链：`2519 run.interrupted → 2520 run.recovered → 2521 agent.runtime.recovered → 2522 runtime.route.attested → 2523 runtime.fallback.denied → 2524 worker.lease.acquired → 2525 worker.fencing.verified → 2526 run.checkpoint.loaded → 2527 worker.duplicate_side_effect.scan`；
- 缺少 terminal duplicate-effect reconciliation、`run.converged`/`run.completed`，冻结 Run 状态仍为 `running`。

## 三、本次真实本地故障注入【事实/边界】

- pause 子进程 PID `29144`，退出 `75`；不同恢复 PID `30372`，退出 `0`；
- checkpoint SHA-256 `11ad7a9dd38b42d8d59eaf504257dcccea56b7ae69f172eb595c2bd161cbd5a1`；静默窗口 `0.35` 秒，目录摘要不变=`True`；旧 worker fenced=`True`；
- side-effect 后故障退出 `73`，恢复退出 `0`；operation `RP-OP-FAILURE-001`；同幂等键副作用次数 `1`；重复抑制=`True`；
- 所有本地收据均标记 `evidence_class=observed_local_process`、`acceptance_eligible=false`。这证明本地实现可运行，不证明江湖编排器或 Claude SDK Session 恢复。

### 3.1 公开提交合并后的补充探针

经逐行审查谢临川公开实现后，合并了 SQLite Memory、OS `kill()`、依赖故障恢复及路径逃逸拒绝探针。补充结果：事件 `23` 条、命令 `13` 条；Memory writer/reader PID `21300/13040`；错误 namespace 退出 `77`；强制终止后副作用计数 `1` 且重复抑制=`True`；依赖退出/恢复 `69/0`；路径逃逸退出 `64`。补充探针仍为 `acceptance_eligible=false`。

## 四、预声明阻断与首轮候选【决定】

`config/candidate-v1.json` 有意保持 `collector_provenance=null`；`config/predeclared-blocker.json` 在任何裁判结果前固定 `RP-BLOCKER-001`。本地预门禁真实返回：

```text
verdict=REJECT
exit_code=42
candidate_sha256=4343af1343a1ba0712582a0a4c67ddfe5cabe3101f3cdf45bf60d2e0f629e1e5
```

该阻断可通过创建不可变 V2 修复；`runtime_probe.gate.remediate` 会关联 V1 SHA-256 且不改写 V1。当前未创建正式 `config/candidate-v2.json`、未伪造 platform attempt 或 Judge event，等待后续独立 Judge 真实退回后再返工。补充探针目录中的 V2 只是 `acceptance_eligible=false` 的本地门禁自检，不是正式候选。

## 五、公开工程提交审查与实质分歧【事实/决定】

- 实际读取两份授权 public manifest，并对每一行形成决定：`evidence/runtime_probe/public-submission-review.json`；
- prompt 中列示谢临川 manifest 为 96 文件，但执行时公开 manifest 已有 128 行；本次按实际读取的 manifest SHA-256 和 128 行审查，不把差异静默平均；
- 林砚早期快照：sequence `5336` / events SHA-256 `d7950a97b07fee5e69daab3f413c5c0e1fc61df009d7ee526d7fa7a9bbf5bfdd`；谢临川较晚快照：sequence `5349` / `3228b7cc97d49a88270052acc7a5e51c2099ceb8613a49c92b62f3e78f060325`；两者作为 moving projection 的历史合法截止保留；
- 本报告采用当前重新冻结的 sequence `6015` / SHA-256 `41171e25f262f44f71aad2273dbac20c556bd807ca95c8ac1ff036aef38ebc40` 作为唯一正式判断截止，不平均计数，也不改写历史快照；
- 采用 `runtime_probe` 为主取证实现；合并谢临川的五角色契约、target schema、SQLite/强制终止/依赖/路径边界探针；拒绝用第二套并行 CLI 覆盖主实现；
- 38/38 Artifact 原始字节事实可合并，但 collect/download 未覆盖全部 Artifact，故 CAM-04 继续 `PARTIAL`。

## 六、CAM-00～CAM-12

| Control | 状态 | 证据边界 |
|---|---|---|
| CAM-00 | NOT_PASS | Mapping artifact exists, but parity, zero traffic, no bypass, single writer and rollback are not proven. |
| CAM-01 | PARTIAL | 26 completed-turn bindings verified; explicit SDK session start/continue lifecycle is incomplete. |
| CAM-02 | NOT_PASS | 5 distinct bound agents are visible, but they are not bound to the five required named roles; role-to-session proof is absent. |
| CAM-03 | PARTIAL | 979/979 projected groups have four platform phases; raw request/result bytes, independent schema denial and result digests are absent. |
| CAM-04 | PARTIAL | 38/38 registered bytes verify; full collect/download lifecycle covers 36 artifacts, not every artifact. |
| CAM-05 | PARTIAL | 14 public messages across 5 actors are visible, not a five-role production flow. |
| CAM-06 | NOT_PASS | Projected Judge/gate event count is 0. |
| CAM-07 | PARTIAL | 1 attempt.created event has rework_of, but no independent Judge causation is visible. |
| CAM-08 | PARTIAL | Committed=4; later cross-session commit→retrieve→use proven=False. |
| CAM-09 | NOT_PASS | Intentional pause/resume event count is 0. |
| CAM-10 | PARTIAL | Platform interruption/recovery chain exists, but terminal duplicate-side-effect reconciliation and convergence are absent. |
| CAM-11 | NOT_PASS | Frozen Run status is running. |
| CAM-12 | NOT_PASS | No complete entrypoint inventory, zero-traffic window, no silent fallback and retirement rollback evidence. |

## 七、假设与待解决风险

### 假设

1. 平台后续追加事件可继续由同一采集器冻结；每次结论只适用于对应 SHA-256 截止。
2. 后续节点会由平台实际绑定质量审计者和独立 Judge；本节点不自行代替。

### 待解决风险

1. 五个两两独立 actor/role/platform Session/SDK Session 生产链未形成；
2. Tool 原始请求、结果摘要、Schema/IAM 拒绝与业务副作用因果不完整；
3. 两份 workflow output 的 collect/download 完整链缺失；
4. Judge `REJECT → revision request → new Attempt → V2 → rejudge` 为 0；
5. 本轮 Memory commit 尚无同值跨新 Session retrieve/use；
6. 平台 intentional pause/resume、checkpoint hash、静默窗口和 SDK continuation 缺失；
7. 中断恢复未终态对账；Run 仍在 running；
8. OpenClaw 历史能力等价、全入口零流量、无旁路、无静默回退及退役回滚未证明。

## 八、工程命令与测试【证据】

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `python -m py_compile ...` | 0 | 语法编译通过 |
| `python run_runtime_probe.py build` | 0 | 冻结平台证据、复核 Artifact、运行两套本地故障探针并生成报告 |
| `python -m unittest discover -s tests -v` | 0 | **Ran 34 tests，OK** |
| `python run_runtime_probe.py gate config/candidate-v1.json` | 42（符合预期） | 首轮预声明阻断真实拒绝 |
| `python run_runtime_probe.py write-manifest` | 0 | 最终 manifest 在本节写入后重建 |
| `python run_runtime_probe.py verify` | 0 | 工程包与冻结证据复核通过，迁移仍为 NO-GO |
| `python run_runtime_probe.py check-manifest` | 0 | 最终摘要复核通过 |

首次全量测试曾因保留的 OpenClaw 上游测试错误地调用其 node-specific manifest 校验器检查本节点 manifest 而退出 `1`（34项中1项错误）；已限定旧测试适用范围、给当前 manifest 增加 `node_key`，随后重跑通过。其后一次 15 项专项复核在措辞修订后、manifest 重建前运行，真实检出 5 个摘要陈旧并退出 `1`；未忽略该结果，先重建 manifest，再全量重跑 34 项并通过。两次失败、原因及处置均登记在 `evidence/runtime_probe/final-command-results.json`；最终执行原始输出见 `evidence/runtime_probe/final-build-test.log`。

