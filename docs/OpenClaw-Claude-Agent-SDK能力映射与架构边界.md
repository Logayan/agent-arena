# 《OpenClaw—Claude Agent SDK 能力映射与架构边界》

**Run：** `run_9226059d74a1`  
**节点：** `openclaw_baseline_mapping`｜OpenClaw 能力基线与迁移映射  
**责任人：** 程观澜｜系统架构师  
**冻结时间：** `2026-09-12T07:21:23.750273+00:00`  
**证据投影：** `public_agent_safe`  
**节点结论：** **能力映射与边界交付有条件通过；Claude Agent SDK 完整迁移验收 `NO-GO`；OpenClaw 退役不批准。**

---

## 0. 正式裁决

```text
node_delivery=CONDITIONAL_PASS_MAPPING_AND_BOUNDARY_DELIVERED
current_claude_only_route=PASS_PLATFORM_ATTESTED
platform_turn_to_sdk_session_binding=PASS_PARTIAL_LIFECYCLE
platform_tool_four_event_lifecycle=PASS_WITH_LIMITATIONS
workspace_file_publication=PASS_NOT_FORMAL_ARTIFACT
public_two_round_collaboration=PASS_TWO_ACTORS
memory_read_and_use=PARTIAL
backend_interruption_recovery=PARTIAL_PLATFORM_RECOVERY_OBSERVED_NOT_CONVERGED_AT_SNAPSHOT

complete_claude_agent_sdk_runtime_migration=NOT_PROVEN
formal_artifact_lifecycle=BLOCKED
five_role_production_flow=BLOCKED
judge_reject_rework_rejudge=BLOCKED
memory_write_read_roundtrip=BLOCKED
intentional_pause_resume=BLOCKED
exactly_once_terminal_reconciliation=BLOCKED
openclaw_retirement=NOT_APPROVED
```

本报告明确保留两条不能合并的事实：

1. 平台事件和 Runtime attestation 支持“**当前活动路由为 `claude_code / agent-sdk-bridge`，非 Claude Runtime 回退被拒绝**”；
2. 当前证据不支持“**完整 Claude Agent SDK Runtime 迁移已经完成**”，也不支持 OpenClaw 已满足退役门禁。

`agent.turn.completed` 绑定中的 `model=gpt-5.6-sol` 是平台 attestation 字段值；它与 `runtime.route.attested` 是两个独立事实。本文**不把二者拼接成端到端 Claude 模型执行证明**。

---

## 1. 证据范围与强度

### 1.1 冻结快照

本交付从平台提供的 `.jianghu-platform-evidence` 读取，并通过 `src/capture_platform_snapshot.py` 在 `events.ndjson` 前后字节一致时冻结。正式包只依赖 `delivery/` 内的快照：

| 项目 | 冻结值 |
|---|---|
| 投影事件数 | `4,395` |
| 平台 metadata 事件数 | `4,403` |
| sequence | `1..4403` |
| 投影过滤缺口 | `687, 812, 1258, 2248, 3898, 3937, 4211, 4329` |
| `events.ndjson` SHA-256 | `3f9453f269a962240931d57f9bd91820bd3f578353e7300648e9f1d4a937f782` |
| critical events | `330`，均可对应到完整投影 |
| Run version / epoch | `8 / 2` |
| 快照时 Run 状态 | `running` |
| Artifact Registry | `[]`，3 字节，0 项 |

sequence 不连续不是擅自补齐的缺陷：快照声明为 `public_agent_safe` 过滤投影，而不是源数据库导出。八个缺口被保留并显式登记；本报告不声称已核验源 Event 数据库。

### 1.2 证据强度

从强到弱使用以下分级：

1. **平台事件＋原始字节**：例如冻结 NDJSON、Artifact Registry、可物化的公开提交文件；
2. **平台事件**：例如 Tool 生命周期、公开协作、Memory read/use、恢复链；
3. **平台 attestation，无源文件原始字节复核**：例如 Runtime Registry 和部署源指纹；
4. **本地探针**：只证明当前交付包或工作区行为；
5. **目标设计契约**：Schema、边界和后续门禁；
6. **未观察**：不解释为能力不存在。

### 1.3 原始字节与 attestation 的边界

`runtime-source-attestation.json`：

- 状态 `passed`；
- 九项检查均为 `true`；
- 记录 13 个生产源文件指纹；
- 声明 Runtime Registry 只构造 Claude 默认 Runtime、拒绝非 Claude 配置、部署无 OpenClaw Runtime 依赖；
- 将 `server/app/openclaw_runtime.py` 和 OpenClaw contract test 标为历史迁移基线 exclusion。

但上述 13 个生产源文件的原始字节不在本平台快照中。本交付只认定为**平台源 attestation**，不表述为独立源码审计通过。

---

## 2. OpenClaw 基线的可知与未知

### 2.1 本次能确认的内容

平台 attestation 明确提到：

- `server/app/openclaw_runtime.py` 是 frozen migration baseline / direct adapter parity 用途；
- 对应 OpenClaw contract test 是 migration baseline regression；
- 产品 Runtime Registry 当前不导入或注册该 OpenClaw adapter。

这些事实足以说明 OpenClaw 在迁移史和 parity 语境中仍是必须处理的历史基线对象。

### 2.2 本次不能确认的内容

当前授权证据没有提供 OpenClaw 的：

- 原始源码和依赖锁；
- 配置、接口和入口清单；
- SDK/会话语义；
- Tool 授权和副作用语义；
- Memory、Checkpoint、Lease、Operation 语义；
- Artifact、Judge、协作、恢复的历史事件样本；
- 实际流量、旁路、单写者和退役回滚记录。

因此，能力映射中的 OpenClaw 历史责任不能被填成“已知等价”或“能力不存在”。统一标记为：

```text
historical_reference_attested / raw_baseline_unknown_current_run
```

---

## 3. 目标架构边界

### 3.1 Claude Agent SDK / Claude Code bridge

负责单 Agent 执行面：

- 模型回合执行；
- SDK Session 打开、继续、关闭；
- Invocation 开始、完成、失败；
- SDK 原生 Tool Use 请求/结果；
- SDK hook、取消、用量和 provider-neutral 执行回执。

它不应独自拥有：Run、Node、Judge、Memory 审批、Artifact Registry、Worker Lease 或 Exactly-once 业务语义。

### 3.2 江湖 Online 控制面

负责产品和组织语义：

- Run、Node、Task、Attempt、Role、platform Session；
- 执行 epoch、重试、暂停和恢复策略；
- 人物身份、两轮公开协作和 synthesis；
- Judge 拒绝、返工、新 Attempt、替代 Artifact 和再裁决；
- Memory 候选、审核、提交、检索和删除治理；
- Runtime Registry、路由策略、状态投影和最终收敛。

### 3.3 受控 Tool gateway

负责所有有副作用工具的治理：

- 输入 Schema；
- allow/deny 授权；
- 凭据隔离、脱敏和最小权限；
- `tool_call_id / operation_id / idempotency_key`；
- 结果摘要、输出摘要和副作用状态；
- 重试、去重、补偿、DLQ 和人工接管。

SDK Tool Use ID 只能作为上游执行标识，不能代替业务 `operation_id` 和 durable idempotency journal。

### 3.4 耐久状态层

必须相互分离而且可关联：

| Store | 主键/核心语义 | 责任 |
|---|---|---|
| Event | `event_id`, sequence, causation | 追加、投影、审计和重放 |
| Artifact | `artifact_id`, version, digest | 不可变产物、下载和复读 |
| Memory | namespace, memory ID/version | 候选、审核、持久化、检索、替代、删除 |
| Checkpoint | Run/Attempt/epoch | 可恢复控制面状态 |
| Lease | Run/epoch/worker/fencing token | 单活动 Worker 和旧 epoch 拒绝 |
| Operation | operation/idempotency key | 副作用终态、去重和补偿 |

文件写入 workspace 不等于 Artifact；Memory 上下文注入不等于 Memory 写回；Tool 事件完整不等于 Exactly-once 已完成。

---

## 4. 能力映射与当前状态

| 能力 | OpenClaw 基线 | Claude SDK / bridge | 江湖控制面 | Tool gateway / durable store | 当前证据与决定 |
|---|---|---|---|---|---|
| Runtime 路由 | 历史 exclusion 被 attestation 提及；原始字节未知 | `claude_code / agent-sdk-bridge` | Registry、入口和 fail-closed fallback | Event / route audit | `PASS_PLATFORM_ATTESTED`，seq `3/4/5/2522/2523` |
| SDK Session / Invocation | 未知 | 应拥有完整 Session/Invocation 生命周期 | 绑定 Run/Node/Attempt/Role/platform Session | Event / Checkpoint | 16 个 turn-completion 绑定，12 个属于本节点；无显式 SDK 生命周期，`PARTIAL` |
| Tool 调用 | 未知 | SDK Tool Use 请求/结果 | 身份、Attempt、Session 关联 | Tool gateway / Operation | 785 Run-wide、371 node 四事件组；原生 SDK/Invocation/结果摘要缺失，`PARTIAL` |
| 文件发布 | 未知 | 可调用文件工具 | file event、submission publication | Workspace / Event | 58 最新 manifest 行已审查；文件发布 `PASS`，不是 Artifact |
| Artifact | 未知 | 非 Registry owner | Artifact 登记与发布状态 | Artifact Registry/object store | Registry 0 项，`BLOCKED` |
| 公开协作 | 未知 | 每个人物独立 turn | submission、round、message、synthesis | Event / public message | 两个 actor 两轮通过；synthesis 未 completed；五角色不满足 |
| Judge/返工 | 未知 | 独立 Judge turn | verdict、gate、新 Attempt、再裁决 | Event / Artifact / decision | 无事件，`BLOCKED` |
| Memory | 未知 | 消费选定上下文 | namespace、审核、提交、检索 | Memory / Event | 读/用有证据；写回轮次无证据，`PARTIAL` |
| 主动暂停恢复 | 未知 | 继续或重建 SDK Session | pause、quiesce、resume、epoch | Checkpoint / Lease / Operation | 无主动暂停事件，`BLOCKED` |
| 后端故障恢复 | 未知 | 续接或重建执行上下文 | epoch、lease、fencing、checkpoint、convergence | Lease / Checkpoint / Operation | seq `2519..2527`，但无终态收敛，`PARTIAL` |
| Exactly-once | 未知 | 提供 Tool Use identity | 协调重试和 epoch | Operation journal / fencing | duplicate scan=`monitoring`，无终态回执，`BLOCKED` |
| OpenClaw 退役 | parity 原始基线未知 | 应覆盖所有批准责任 | 零流量、无旁路、单写者、回滚治理 | 路由与流量审计 | 当前路由通过不等于退役通过，`NOT_APPROVED` |

机器可读明细见 `mapping/capability_mapping.json`。

---

## 5. Runtime 路由和 Session 绑定

### 5.1 路由

观察到两组初始/恢复后路由事件：

| sequence | event | 结果 |
|---:|---|---|
| 3 | `agent.runtime.ready` | `runtime=claude_code`, `mode=agent-sdk-bridge` |
| 4 | `runtime.route.attested` | `authorization_decision=claude_code_only`, epoch 1 |
| 5 | `runtime.fallback.denied` | `authorization_decision=deny`, `status=passed` |
| 2522 | `runtime.route.attested` | 恢复后 epoch 2 Claude-only |
| 2523 | `runtime.fallback.denied` | 恢复后 fallback denied |

据此可通过“当前路由”门禁，但不能上调“完整迁移”。

### 5.2 Session 绑定

`runtime-attestation.json` 提供：

- Run-wide `16` 个 `agent.turn.completed` 到 SDK Session 的绑定；
- `4` 个 actor；
- `16` 个不同 SDK Session；
- 本节点 `12` 个绑定、`2` 个 actor；
- 本节点 sequence：
  `704, 831, 879, 890, 939, 954, 3926, 4243, 4282, 4292, 4379, 4390`。

校验器逐项核对：

- attestation 的 event sequence / event ID / source hash；
- `agent.turn.completed` payload 中 actor、node 和 platform Session；
- nested runtime 的 SDK `session_id`、`session_key`、runtime 和 model 字段。

限制：

- 无 `sdk.session.opened/continued/closed`；
- 无 `sdk.invocation.started/completed/failed`；
- 无 SDK Session close 或异常清理证据；
- `model` 字段不作为 provider execution receipt。

---

## 6. Tool 生命周期

### 6.1 Run-wide 与本节点必须分开

| 范围 | 完整四事件组 | completed | failed | Read | Bash | Edit | Write |
|---|---:|---:|---:|---:|---:|---:|---:|
| Run-wide | 785 | 720 | 65 | 333 | 271 | 115 | 66 |
| 当前节点 | 371 | 324 | 47 | 196 | 102 | 28 | 45 |

每个 group 必须且只允许各一条：

```text
agent.tool.authorization.decided
→ agent.tool.started
→ agent.tool.completed
→ agent.side_effect.verified
```

校验器还要求：

- sequence 顺序严格递增；
- `tool_call_id / tool_name / agent_id / node_key / platform_attempt_id / platform_session_id / session_key` 一致；
- authorization 与 side-effect 的 `operation_id / idempotency_key` 一致；
- completed 对应 `side_effect_status=completed`；
- failed 对应 `side_effect_status=failed_preserved`；
- 退出码存在时前后一致。

### 6.2 限制

- 785 个 authorization 全为 `allow`，未验证 deny；
- 本节点 371 个 group 中，240 个对应冻结绑定集中的 platform Session，131 个在截止点没有 terminal SDK binding；
- Tool 事件没有 `sdk_session_id`、`invocation_id`、`result_digest`、`output_sha256`；
- 因此只能认定平台 Tool lifecycle 完整，不能认定 SDK 原生 Tool 全链路或 Exactly-once 完成。

---

## 7. 文件、公开提交与 Artifact

### 7.1 最新提交逐行审查

审查对象是当前两个公开 manifest，而不是旧 34 行 review：

| 人物 | manifest SHA-256 | 变更行 | 非删除 | 删除 marker | publication |
|---|---|---:|---:|---:|---|
| 程观澜 | `478e89e2f908e8573d301c0d895fb88432329ff528dfb21dcb4405760111aee1` | 31 | 26 | 5 | seq 4255 / `evt_197d3d1e16ed` |
| 谢临川 | `3c98a67dec4388a49d9afd171c2e57145281d47c7b43d5161558a50c87e048c5` | 27 | 27 | 0 | seq 4256 / `evt_288ddad872da` |

总计：

- 58 个 manifest change rows；
- 53 个非删除行；
- 5 个删除 marker；
- 45 个非删除行从 collaboration export 读取原始字节并复算匹配；
- 8 个非删除行的 manifest 与 platform file event 摘要/大小匹配，但 public export 未物化原始字节；
- 对这 8 行**不声称独立字节审计**；
- 删除 marker 以 manifest＋platform deletion event 为准，export 中残留的旧字节不被当作当前状态。

每行的 `adopt / revise / replace / preserve_deletion / reject_*` 决定见 `evidence/submission_review.json`。

### 7.2 Artifact 仍阻塞

冻结 `artifact-registry.json`：

```json
[]
```

- 3 字节；
- SHA-256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`；
- metadata `artifact_count=0`。

没有 `artifact_id`、registry/materialized digest pair、下载和复读回执。本交付文件只是 formal candidate files，不是本次 Run 已登记 Artifact。

---

## 8. 两轮公开协作

### 8.1 历史 epoch 1 cycle

- submissions：843、844；
- round 1：start 845，messages 900/901，complete 902；
- round 2：start 903，messages 964/965，complete 966；
- synthesis started：967；
- 无 `team.synthesis.completed`。

### 8.2 当前 epoch 2 cycle

- submissions：4255、4256；
- round 1：start 4257，messages 4302/4303，complete 4304；
- round 2：start 4305，messages 4400/4401，complete 4402；
- synthesis started：4403 / `evt_91be130e1a12`；
- 无 `team.synthesis.completed`。

两个 cycle 都具备：

- 两个 actor；
- 每轮一条 challenge 和一条 reply；
- 双向消息；
- 两轮完成事件。

当前节点满足“架构与 SRE 两人两轮公开通信”，但不满足用户要求的产品、架构、工程、质量、Judge 五角色真实生产流，也没有完成 synthesis 终态。

### 8.3 保留的实质分歧

没有静默平均以下分歧：

1. **当前 Claude-only route**：通过；
2. **完整 Claude Agent SDK 迁移**：未证明；
3. **OpenClaw 退役**：不批准；
4. **恢复状态**：不是 PASS，而是 `PARTIAL_PLATFORM_RECOVERY_OBSERVED_NOT_CONVERGED_AT_SNAPSHOT`；
5. **model 字段**：只作为字段事实，不能与 route 合成 provider execution 证明；
6. **文件与 Artifact**：严格拆分；
7. **Run-wide 与 node-scoped Tool 数量**：分别报告，不互相替代。

---

## 9. Memory、Judge、暂停与恢复

### 9.1 Memory

| 范围 | retrieved | used | distinct Memory IDs |
|---|---:|---:|---:|
| Run-wide | 168 | 128 | 32 |
| 当前节点 | 104 | 96 | 16 |

本节点 96 条 use 都能在公开投影中找到相同 `memory_id / reader_session_id / value_sha256` 的 retrieval。Run-wide 128 条 use 均能按 `memory_id / value_sha256 / agent_id` 对应已有 retrieval，其中 112 条还能在投影中同 Session 对应，16 条的同 Session retrieval 不在过滤投影内。该证据证明平台读取并使用已有 Memory；它不证明本次 Run 新写入，也不把 filtered gap 补造成事件。

缺失：candidate、review、commit、persist、后续不同 Session 回读、namespace deny、supersede、tombstone。

### 9.2 Judge / rework / rejudge

在 4,395 条投影中没有：

- `judge.verdict`；
- `gate.rejected`；
- `revision_request` / `revision.requested`；
- `rework.requested`；
- replacement Artifact；
- `rejudge.completed`。

因此完全阻塞，不能以本地测试中的 reject 分支替代平台 Judge 状态机。

### 9.3 主动暂停恢复

没有 `run.pause.requested`、`run.paused`、`run.resumed`。后端中断和主动暂停是不同的产品语义，不能互换。

### 9.4 后端中断恢复

观察到的链：

```text
2519 run.interrupted
2520 run.recovered / execution_epoch=2
2521 agent.runtime.recovered
2522 runtime.route.attested / claude_code_only
2523 runtime.fallback.denied / deny
2524 worker.lease.acquired / acquired
2525 worker.fencing.verified / old_epoch_denied
2526 run.checkpoint.loaded / loaded
2527 worker.duplicate_side_effect.scan / monitoring
```

这证明控制面完成部分恢复步骤，但缺失：

- `sdk.session.continued` 或显式重建绑定；
- duplicate side-effect scan 的 terminal reconciliation；
- 外部副作用复读与 exactly-once receipt；
- `run.converged` 或 `run.completed`。

正式状态：

```text
PARTIAL_PLATFORM_RECOVERY_OBSERVED_NOT_CONVERGED_AT_SNAPSHOT
```

---

## 10. 退役门禁

在 OpenClaw 退役前，至少需要：

1. 原始 OpenClaw 能力基线与 parity corpus；
2. Claude Runtime 源码原始字节和 Registry/entrypoint/deployment 独立审计；
3. SDK Session、Invocation、Tool native identity 全生命周期；
4. 五角色真实生产流；
5. formal Artifact create/register/publish/download/reread；
6. Judge reject→new Attempt→replacement Artifact→rejudge；
7. Memory write→later Session read/use→tombstone；
8. intentional pause/quiesce/resume；
9. 故障注入后的 terminal reconciliation 和 Run convergence；
10. 所有入口 OpenClaw 零流量、无旁路、单写者、失败关闭和回滚演练。

当前 P0/P1 明细见 `gaps/migration-gap-list.json`。

---

## 11. 工程实现与复核

统一入口：

```text
python run_acceptance.py verify
python run_acceptance.py write-receipts
python run_acceptance.py write-manifest
python run_acceptance.py check-manifest
python run_acceptance.py print-verdict
```

验证器采用 fail-closed 标准库实现，检查：

- 快照摘要、sequence、filtered gaps、event ID、source hash；
- critical-event correspondence；
- Runtime route、source attestation 和 16 个绑定；
- 785/371 Tool 生命周期不变量；
- 两个公开协作 cycle；
- Memory read/use；
- 空 Artifact Registry 原始字节；
- 最新两个 manifest 的 58 行 review；
- Judge、暂停、SDK continuation、Run convergence 的缺失；
- mapping/gaps 与冻结计数一致；
- 整包 SHA-256 manifest。

目标事件契约位于 `schemas/runtime-event-envelope.schema.json`。它被明确标为 `TARGET_ONLY`；当前投影不满足该强契约，不能把 Schema 存在误写成 Runtime 已实现。

---

## 12. 最终决定

本节点交付可以作为后续全链路验收的能力基线、边界和 P0 门禁输入；不能用于签发完整迁移通过。

```text
能力映射与架构边界=有条件通过
当前 Claude-only Runtime 路由=平台事件/attestation 通过
Claude Agent SDK 完整迁移=未证明
OpenClaw 退役=不批准
```
