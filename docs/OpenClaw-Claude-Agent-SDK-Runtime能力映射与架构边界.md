# OpenClaw—Claude Agent SDK Runtime 能力映射与架构边界

**版本：** v2.0.0（系统架构与运行保障合议正式版）  
**Run：** `run_6940048dd30f`  
**节点：** `openclaw_baseline_mapping`  
**Attempt：** `attempt:run_6940048dd30f:openclaw_baseline_mapping:epoch1:loop1:node1`  
**冻结证据：** `attempt-415cb8b318fda11f`，`public_agent_safe` sequence `1..94`  
**参与者：** 程观澜｜系统架构师；谢临川｜平台运维与站点可靠性工程师  
**发起人现场补充意见：** 无；本节点不扩展验收范围、不降低证据门槛、不引用私享审计正文。

---

## 0. 正式裁决【决定】

```text
mapping_delivery=CONDITIONAL_PASS_EVIDENCE_BOUND_MAPPING

public_event_sequence_and_identity=PASS_94_OF_94
critical_full_object_correspondence=PASS_92_OF_92
snapshot_cross_file_atomicity=OPEN_METADATA_93_VS_EVENTS_94

registered_source_artifact_raw_bytes=PASS_13_OF_13
registered_source_artifact_lifecycle=PASS_13_OF_13
current_node_candidate_artifact_lifecycle=BLOCKED_0_AT_SEQUENCE_94

current_runtime_registry=CLAUDE_CODE_ONLY
current_route_probe_window=PASS_10_OF_10_WINDOW_ONLY
openclaw_runtime_fallback_probe=PASS_FAIL_CLOSED
claude_agent_sdk_dependency=PASS_EXACT_0.3.268
completed_turn_sdk_binding=BLOCKED_0
real_tool_execution_lifecycle=BLOCKED_0

public_collaboration_content=PASS_4_MESSAGES_2_ACTORS_2_ROUNDS
public_collaboration_frozen_event_attestation=BLOCKED_0_AT_SEQUENCE_94
judge_reject_rework_rejudge=BLOCKED
memory_new_context_roundtrip=BLOCKED
intentional_pause_resume=BLOCKED
failure_recovery_exactly_once=BLOCKED
run_terminal_convergence=BLOCKED_RUNNING
historical_openclaw_baseline=BLOCKED_RAW_BYTES_ABSENT

CLAUDE_AGENT_SDK_FULL_RUNTIME_MIGRATION=NO_GO
OPENCLAW_RETIREMENT=NOT_APPROVED
```

**结论：** 本节点已交付证据绑定的能力映射、架构边界、事件模型、持久化边界、残余路径及可执行校验器；但不能证明江湖 Online 已完整使用 Claude Agent SDK 承担全部 Agent Runtime，也不能批准 OpenClaw 退役。

工程映射通过不等于迁移验收通过。源码中存在能力路径不等于当前 Run 已执行；启动 IAM/路由探针不等于真实 Tool、Session、协作、Memory 或恢复闭环。

---

## 1. 取证范围与证据等级

### 1.1 实际读取【事实与证据】

本节点实际读取并校验：

```text
.jianghu-platform-evidence/snapshots/attempt-415cb8b318fda11f/
├─ events.ndjson
├─ critical-events.json
├─ artifact-registry.json
├─ runtime-attestation.json
├─ runtime-source-attestation.json
├─ run-metadata.json
├─ run-lineage.json
└─ projection-omissions.json
```

并按 Registry 的 `materialized_path` 读取全部 13 份正式原始字节，逐项复算字节数与 SHA-256。逐 Artifact 的 ID、source sequence/event ID/source hash、路径、摘要和三段生命周期见 `evidence/evidence-index.json` 与 `evidence/verification-receipt.json`。

### 1.2 证据等级【决定】

| 等级 | 可支持的结论 | 不可替代 |
|---|---|---|
| 当前事件行为 | 当前 Run 在冻结截止前真实发生的公开事件 | 不能由源码声明替代 |
| Registry 原始字节 | 指定源码/部署输入确有这些字节和实现路径 | 不能证明分支已经执行 |
| Attestation | 平台对 Runtime、源码集合或 Session binding 的登记 | 不能证明未登记仓库文件不存在 |
| 公开通信输入 | 本节点两位参与者已交换并接受的公开意见 | 不等于 sequence 94 内已有通信事件 |
| 目标设计 | 推荐的职责边界、事件模型和关闭条件 | 不能记作当前系统事实 |

`public_agent_safe` 是公开安全投影，不是源数据库全量导出。`source_event_sha256` 在投影内可校验格式与唯一性；因私有源事件原始字节不可见，本节点不声称独立重算该字段。

---

## 2. 冻结快照完整性【事实、证据与风险】

独立复核结果：

```text
events.ndjson rows=94
sequence=1..94 contiguous
unique event_id=94/94
unique source_event_sha256=94/94
projection omissions=0
critical full-object exact=92/92
run-metadata.event_count=93
run status=running
```

文件摘要：

| 文件 | Bytes | SHA-256 |
|---|---:|---|
| `events.ndjson` | 95,579 | `f2663c4ec156deb9eecc72b5c80d49f6d2879128e5c16ed72e0a999d2ca4891b` |
| `critical-events.json` | 94,542 | `dd9dbf92f5a805440e3edffef8b61f4035a0d97d8120997a949d37f9343c2372` |
| `artifact-registry.json` | 14,106 | `aaa67ba117215881a836eae95b59ff768d5dfed294ebb0e44b2e232e8e8b68b9` |
| `runtime-attestation.json` | 1,326 | `5ab05e98d8eaeede8bf85a0fc3655d4fbefd6f8e259f49e437b2b161c7418a64` |
| `runtime-source-attestation.json` | 3,691 | `c43e907bb1c0b98ed70dda849a50da3d3282a1ca9a6d740b18050a671161c852` |
| `run-metadata.json` | 596 | `e56fe3df6331ce8027db8d78cd05e99220d3defcbc6136a9e411d7fb11080d39` |
| `run-lineage.json` | 197 | `e00b0d0e6ffb1f0f964cee6c58cc5c15a0627eee2025a97e8f6953947cf27a0b` |
| `projection-omissions.json` | 232 | `91acb4b0f30267643a1442391038830c6e43cae2d682353219223d6b5097e085` |

**未关闭风险：** 同一冻结目录中事件投影为 94 行，而 metadata event_count 为 93。事件流自身的连续性、身份唯一性和 92/92 critical 对应判定 PASS；跨文件原子性不判 PASS，不用该快照做 sequence 94 附近的终态敏感推断。

---

## 3. 生产源码与部署输入 Artifact【事实与证据】

Registry 共 13 项：

| source seq | Artifact ID | 路径 | Bytes | SHA-256 |
|---:|---|---|---:|---|
| 2 | `artifact_fa7bed6afb42` | `server/app/agent_runtime_registry.py` | 2,587 | `2ab7f42bab2d80d6ee0e5adf39a5b3965ee02c8ffacffadda297128e062f50e3` |
| 5 | `artifact_642f67605eab` | `server/app/main.py` | 141,439 | `8c699a216aec032addeeef7c1acb7f59c5c2c8eaf96e55e6925d4b40051d7566` |
| 8 | `artifact_884782192bec` | `server/app/platform_executor.py` | 295,920 | `faeb25ed535cdd96f7050ba7ae5f4b50381303211a051d3851aaa3728b5d09b2` |
| 11 | `artifact_f7b229debd94` | `server/app/platform_store.py` | 291,489 | `a0667d6ac371806930b1df9104fd295270201bb257ab4ecedae43cc3d62e7b89` |
| 14 | `artifact_de3b19abe481` | `server/app/claude_code_runtime.py` | 46,405 | `79efd4215c2c351357c58dbbf21465d6dc02046bef470cf5208a9b54e73846fc` |
| 17 | `artifact_4972d347b67b` | `server/claude_agent_runtime/bridge.mjs` | 25,426 | `28910db5693a4a1b26e16e278fe2c7a210b8177cdf870d656142083c56ec2abb` |
| 20 | `artifact_c3d918b43572` | `server/claude_agent_runtime/package.json` | 354 | `d6440574ed1ad60d750198580b6989636345f02de6eec4a1b0f21999cc807cd8` |
| 23 | `artifact_84387ee84712` | `server/claude_agent_runtime/package-lock.json` | 53,661 | `a6d66ae59fe8f6a6df6574f7b3c418ba669a2f65a41b82f2ccd368c8054f10a1` |
| 26 | `artifact_4d0828bcd70a` | `client/src/App.vue` | 267,547 | `e0963a924852d1c26f2a9900c9ff575bcfc9e1ad79de7f538fdc922a78bfdf07` |
| 29 | `artifact_8deec74b6eb1` | `client/src/api.ts` | 21,207 | `9adbd8dcaaa090fadbf0a22a7001fdd09799a70d50e181ac624f78b14a1e7984` |
| 32 | `artifact_df2d04b40371` | `Dockerfile` | 2,899 | `19ae22a000046464e5becea5d6fde36cda5467c1fc65eb07d6073b830c6a1f8a` |
| 35 | `artifact_3a7aa238ae26` | `compose.yaml` | 4,262 | `de89820b7b94c13f65656ccfbb0ae8b3bbce6506f2fd0a1cd6b57cd77fcfddd4` |
| 38 | `artifact_7947e3200fe1` | `.env.docker.example` | 794 | `fe74a6e1bd2d79f9310a74d5a2eff003ca064619e94977b79f31f1821f60b125` |

每项均满足：

```text
expected_sha256
= registry observed_sha256
= independently recomputed_sha256

artifact.created → artifact.collected → artifact.download.verified
```

生命周期为 sequence `2..40`，sequence 41 汇总 `13/13 passed`。

**边界：** 以上 13/13 只指已登记的生产源码及部署输入，不是当前节点新报告包。本节点候选截至 sequence 94 没有平台 Artifact ID，故 `current_node_candidate_artifact_lifecycle=BLOCKED_0`。

---

## 4. 当前 Runtime 路由【事实与证据】

Runtime attestation：

```text
runtime=claude_code
mode=agent-sdk-bridge
bridge_version=0.3.268
claude_code_version=2.1.268
sdk_dependency=@anthropic-ai/claude-agent-sdk@0.3.268
session_binding_count=0
model_attestation_field=gpt-5.6-sol
```

- sequence `77..86`：`normal/parallel/judge/rework/recovery/retry/scheduled/callback/manual/background` 十入口均为 `claude_code`。
- sequence `87`：汇总 `openclaw_traffic_count=0`、`dual_write_count=0`、`silent_fallback_count=0`、`single_writer=true`、`fail_closed=true`。
- sequence `88`：未注册 OpenClaw Runtime 请求失败关闭。
- sequence `89`：Claude Runtime 回滚健康检查通过。
- sequence `90`：独立 `OpenClawGateway` policy probe 被拒绝，副作用未开始。

观察窗为 `2026-09-15T06:31:50.236023Z` 至 `06:32:06.454497Z`，约 `16.218474` 秒。这只证明启动短窗内十入口路由，不证明长期生产零流量、无旁路或正式退役。

`runtime=claude_code` 与 `model=gpt-5.6-sol` 是两个独立字段。本报告只确认 Claude Agent SDK/Claude Code bridge 路由，不将其改写成底层 Anthropic Claude 模型身份已获证明。

---

## 5. OpenClaw 实际基线【事实、证据不足与决定】

### 5.1 当前可证事实

在上述短窗中，OpenClaw 未承担十个登记入口的生产 Runtime 执行；生产 Registry 对非 `claude_code` 配置失败关闭。登记的 package-lock、Dockerfile 和 compose 未显示 OpenClaw Runtime 依赖或启动配置。

### 5.2 历史能力不可审计

`runtime-source-attestation.json` 只把以下路径列为 `historical_exclusions`：

```text
experiments/openclaw_baseline/openclaw_runtime.py
server/tests/runtime_contract/test_openclaw_runtime_contract.py
```

两者原始字节没有进入本快照 Registry。因此不能从路径名、当前 Claude 实现或产品文档反推历史 OpenClaw 的 Session、Tool、文件、协作、Memory、暂停、恢复与持久化语义。

```text
OPENCLAW_HISTORICAL_BASELINE=BLOCKED_RAW_BASELINE_NOT_IN_REGISTRY
```

这表示证据不足，不表示认定 OpenClaw 历史上没有这些能力。

---

## 6. 能力映射与架构边界【决定】

| 能力 | Claude Agent SDK 执行面 | 江湖 Online / 工具网关控制面 | 当前状态 |
|---|---|---|---|
| Runtime 回合 | `query({prompt, options})` | Run、Node、Task、Attempt 调度与 Registry | 短窗路由 PASS；completed turn BLOCKED |
| Session | `persistSession`、`resume`、SDK session ID | `agent_id:session_key` 映射、审计、平台 Session | 源码存在；binding=0 |
| Tool | SDK Tool Use/Result、MCP Server | Schema、IAM、路径边界、事件与副作用回执 | IAM 探针 PASS；真实 Tool BLOCKED |
| 文件 | workspace Read/Write/Edit/Bash | delivery 提升、Artifact Registry、Manifest、下载复算 | 源码 Artifact 13/13；当前候选 BLOCKED |
| 协作 | 各角色独立模型回合 | dossier、公开消息、轮次、综合与决定 | 内容级 PASS；冻结事件级 BLOCKED |
| Judge | 独立 Judge 模型回合 | gate、返工 Attempt、Artifact supersession | BLOCKED |
| Memory | 消费获准注入上下文 | candidate/review/commit/version/namespace/retrieve/use | 源码存在；运行 BLOCKED |
| Pause | 取消进程、可选 Session resume | drain、Checkpoint Artifact、静默、resume/load | 源码存在；运行 BLOCKED |
| Failure recovery | 重派或续接回合 | execution epoch、lease、fencing、idempotency、reconciliation | 源码存在；运行 BLOCKED |
| 持久化 | SDK Session state 与引用 | Event/Run/Task/Artifact/Memory/Checkpoint authority | 源码与投影部分通过；终态 BLOCKED |

机器可读明细：`mapping/capability-mapping.json`。

### 6.1 权威边界

1. **Claude Agent SDK** 承担单 Agent 回合、SDK Session、SDK Tool 协议和 MCP 接入。
2. **江湖 Online** 承担 Run/Node/Task/Attempt、角色身份、公开协作、Judge/Gate、Memory 审批、暂停恢复、失败恢复和终态收敛。
3. **jianghu_workspace 网关** 承担工具 allowlist、Schema、路径和 symlink 边界、凭据隔离命令环境、超时及文件/命令副作用入口。
4. **耐久状态层** 承担 Event、Artifact、Memory、Checkpoint、operation/idempotency identity、lease/fencing；聊天文本和临时 workspace 文件不能替代权威状态。

---

## 7. Tool 与当前行为缺口【事实】

sequence `46..76` 为 6 个 Agent × 5 项启动 IAM 探针：

```text
Read allow=6
Write allow=6
Edit allow=6
Bash allow=6
OpenClawGateway deny=6
IAM samples=30
side_effect_status=not_started for all 30
```

sequence 90 另有 1 条独立 policy probe deny。因此 authorization.decided 总数为 31（allow=24，deny=7），但冻结点：

```text
agent.turn.completed=0
agent.tool.started=0
agent.tool.completed=0
agent.side_effect.verified=0
session_binding_count=0
```

授权失败关闭通过，不能替代真实 SDK Tool Request/Result、Invocation/Session 绑定、请求结果摘要及副作用终态。

---

## 8. 公开协作与工程提交合并【事实、差异与决定】

### 8.1 隔离贡献

- 程观澜提交 14 个公开工程文件；
- 谢临川提交 45 个公开工程文件；
- 两份 manifest 共 59 个路径已逐项登记采用、合并、重新生成或不复制决定，见 `collaboration/submission-review.json`。

最终采用一个正式报告、一个能力映射、一个缺口真相源、一个验证器和一个 self-excluding Manifest；没有保留两套并行权威。SRE 重复冻结快照与 13 份原始 Artifact 未二次复制，验证器直接读取 `.jianghu-platform-evidence` 权威字节。

### 8.2 两轮公开通信

平台输入提供两位参与者两轮 4 条公开 challenge/reply，已形成非空综合，见 `collaboration/public-communication-record.json`。统一接受：

- `CONDITIONAL_PASS_EVIDENCE_BOUND_MAPPING / NO_GO`；
- 13/13 只指登记源码及部署输入；
- 当前候选 Artifact 生命周期必须单列 BLOCKED；
- 94 条事件自身完整性与 metadata 偏斜必须分开；
- 十入口结果只限约 16 秒探针窗；
- Runtime 与 model 字段不得拼接解释。

但 sequence `1..94` 中：

```text
agent.message.sent=0
team.communication.round.started=0
team.communication.round.completed=0
synthesis completed=0
```

故最终拆分为：

```text
content_level_two_round_exchange=PASS
frozen_runtime_event_attestation=BLOCKED
```

### 8.3 保留的实质分歧

1. 架构初稿把短窗问题列 P1；运行保障认为长期零流量是退役 P0。最终采用 P0，因为退役是不可由启动短窗覆盖的生产安全决定。
2. 运行保障缺口表未单列当前候选 Artifact；架构侧坚持单列。最终保留独立 P0，避免以 13 份源码 Artifact 替代本节点交付生命周期。
3. 运行保障单列 Run 终态；架构初稿只在恢复缺口中隐含。最终保留独立 P0。
4. 因此最终缺口不是对两个“12项”求平均，而是显式扩充为 `13项：P0=11，P1=2`。

---

## 9. 事件模型【目标设计，不是当前行为】

正式事件至少使用 `event_id/run_id/sequence/type/category/created_at/payload`；对 Tool、Session 与恢复相关事件，payload 应包含：

```text
platform_attempt_id
execution_epoch
agent_id
platform_session_id
claude_sdk_session_id
sdk_invocation_id
tool_call_id
operation_id
idempotency_key
request_sha256
result_sha256
status
```

最小闭环：

| 事件族 | 必需链 |
|---|---|
| Turn | `agent.turn.started → agent.turn.completed`，完成事件绑定 SDK Session/Invocation |
| Tool | `schema.validated → authorization.decided → started → completed → side_effect.verified` |
| Artifact | `artifact.created → artifact.collected → artifact.download.verified`，同一 ID/摘要 |
| Collaboration | `member.completed → dossier → round1 → round2 → synthesis → decision` |
| Judge | `judge REJECT → gate.rejected → new Attempt → superseding Artifact → rejudge` |
| Memory | `candidate → reviewed → committed → persisted → new Session retrieved → used` |
| Pause | `pause_requested → drained → checkpoint Artifact → paused → silence → resumed → loaded` |
| Recovery | `interrupted → new epoch/lease → fencing → checkpoint → terminal reconciliation → duplicate=0 → converged` |

Schema：`schemas/runtime-event-envelope.schema.json`、`schemas/runtime-capability-map.schema.json`。

---

## 10. 残余 OpenClaw 路径【事实与风险】

在 13 份登记源码中发现 OpenClaw 文本残余，验证回执按路径和行号登记。主要类别：

- `server/app/main.py`：旧 `/api/platform/openclaw/status` 路由及旧错误兼容；
- `server/app/platform_executor.py`：迁移校验、禁止扫描和负向探针；
- `server/app/platform_store.py`：旧 runtime 值、旧事件名和数据迁移兼容；
- `client/src/App.vue`：旧事件/UI 文案兼容。

登记范围内未发现 OpenClaw Adapter 被生产 Registry 构造、OpenClaw Runtime package 依赖、Docker/compose 启动配置或前端 API client 调用旧 status 路径。

这些残余不等于当前 OpenClaw Runtime 有流量，但意味着“零可执行依赖”“零 API/事件兼容”“零命名残余”是不同退役层级，必须分别关闭。

---

## 11. 假设与限制

1. 13 项 Registry 覆盖的是 attestation 定义的生产 Runtime 源码与部署输入；本节点不能证明未登记仓库文件不存在。
2. 十入口集合按平台探针定义视为当前产品入口集合；长期真实流量仍需生产周期证据。
3. Source 中的 Session、Memory、Checkpoint、fencing 与 reconciliation 分支可被调用；当前没有相应行为事件证明。
4. PostgreSQL/SQLite 分支和部署配置的生产实际使用情况未在本节点执行数据库恢复测试。
5. 本节点当前工具真实创建了交付文件并运行测试，但这些后续工具调用不能倒灌为 sequence 94 冻结证据。

---

## 12. 缺口与后续门禁【风险】

最终缺口真相源：

```text
gaps/迁移缺口清单.md
gaps/migration-gaps.json

OPEN=13
P0=11
P1=2
```

最关键门禁：历史 OpenClaw 原始基线、长期零流量、五角色 completed-turn SDK binding、真实 Tool 链、当前候选 Artifact 下载闭环、事件级公开协作、Judge 返工、Memory 新 Session 回读、主动暂停、故障恢复 exactly-once、Run 终态、快照原子性和残余接口退役。

在全部 P0 关闭并由后续独立 Judge 基于新冻结证据裁决前：

```text
CLAUDE_AGENT_SDK_FULL_RUNTIME_MIGRATION=NO_GO
OPENCLAW_RETIREMENT=NOT_APPROVED
```
