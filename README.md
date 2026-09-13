# OpenClaw 能力基线与 Claude Agent SDK 迁移映射验收包

**Run：** `run_9226059d74a1`  
**Node：** `openclaw_baseline_mapping`  
**责任人：** 程观澜｜系统架构师

## 结论

```text
node_delivery=CONDITIONAL_PASS_MAPPING_AND_BOUNDARY_DELIVERED
current_claude_only_route=PASS_PLATFORM_ATTESTED
complete_claude_agent_sdk_runtime_migration=NOT_PROVEN
backend_interruption_recovery=PARTIAL_PLATFORM_RECOVERY_OBSERVED_NOT_CONVERGED_AT_SNAPSHOT
openclaw_retirement=NOT_APPROVED
```

本包不使用模拟事件。正式结论来自冻结的本次 Run `public_agent_safe` 平台投影、Runtime attestation、两个最新公开工程 manifest 及可读取的原始文件字节。

## 冻结证据

| 项目 | 值 |
|---|---|
| 投影事件 | 4,395 |
| metadata event count | 4,403 |
| sequence | `1..4403` |
| filtered gaps | `687, 812, 1258, 2248, 3898, 3937, 4211, 4329` |
| event SHA-256 | `3f9453f269a962240931d57f9bd91820bd3f578353e7300648e9f1d4a937f782` |
| SDK Session bindings | 16 Run-wide / 12 node |
| Tool groups | 785 Run-wide / 371 node |
| Memory | 168/128 Run-wide retrieved/used；104/96 node |
| Artifact Registry | 0，原始内容 `[]` |
| 当前公开协作 | 两 actor、两轮、4 消息；synthesis started，未 completed |
| Run status at cutoff | `running`, execution epoch 2 |

## 关键边界

1. `runtime.route.attested=claude_code_only` 证明当前平台路由事实，不证明完整历史能力迁移。
2. binding 中 `model=gpt-5.6-sol` 只是 attestation 字段，不能与 route 拼接为端到端 Claude model execution proof。
3. workspace 文件和 engineering submission 不是 formal Artifact。
4. Tool 四事件链完整不等于 SDK native linkage 或 exactly-once 终态完成。
5. Memory read/use 不等于本次 Run 完成 write/read roundtrip。
6. 后端 interruption recovery 不等于 intentional pause/resume。
7. sequence gaps 是公开过滤投影边界，不得伪造补齐，也不代表源数据库已验证。

## 目录

```text
README.md
pyproject.toml
run_acceptance.py
runtime_acceptance/
  __init__.py
  verifier.py
src/
  capture_platform_snapshot.py
tests/
  test_runtime_acceptance.py
docs/
  01_架构视角隔离盘点.md
  02_运行保障视角隔离盘点.md
  OpenClaw-Claude-Agent-SDK能力映射与架构边界.md
mapping/
  capability_mapping.json
gaps/
  migration-gap-list.json
schemas/
  runtime-event-envelope.schema.json
evidence/
  platform_snapshot/
  platform_snapshot_index.json
  snapshot_history.json
  submission_review.json
  final_verification.json
  runtime_session_bindings.json
  tool_lifecycle_summary.json
  public_collaboration.json
  build_test_run.log
artifacts/
  sha256_manifest.json
```

`.jianghu-platform-evidence/` 是平台输入副本，不进入正式 package manifest。验收代码只读取 `delivery/evidence/platform_snapshot/`，不依赖父目录、环境变量、Token 或 Provider 凭据。

## 两个最新公开 manifest 的处理

- 程观澜：31 change rows；manifest SHA-256 `478e89e2f908e8573d301c0d895fb88432329ff528dfb21dcb4405760111aee1`；publication sequence 4255。
- 谢临川：27 change rows；manifest SHA-256 `3c98a67dec4388a49d9afd171c2e57145281d47c7b43d5161558a50c87e048c5`；publication sequence 4256。
- 共 58 行：53 非删除、5 删除 marker。
- 45 个非删除文件可从公开 export 读取并复算匹配；8 个只取得 manifest＋platform file event 对应，原始字节未物化，不声称独立 byte audit。
- 每行决定见 `evidence/submission_review.json`。

## 运行

所有命令必须以本目录 `delivery/` 为 workdir：

```bash
python -m py_compile run_acceptance.py runtime_acceptance/__init__.py runtime_acceptance/verifier.py src/capture_platform_snapshot.py tests/test_runtime_acceptance.py
python -m unittest discover -s tests -v
python run_acceptance.py verify
python run_acceptance.py write-receipts
python run_acceptance.py write-manifest
python run_acceptance.py check-manifest
python run_acceptance.py print-verdict
```

### 命令语义

- `verify`：只读验证冻结证据、映射、缺口和 manifest review；
- `write-receipts`：验证后刷新四个生成式 evidence receipts；
- `write-manifest`：为除 manifest 自身、平台输入副本和 Python cache 外的正式文件生成 SHA-256；
- `check-manifest`：检查正式包路径集合、字节数和 SHA-256；
- `print-verdict`：输出节点交付、迁移和 OpenClaw 退役裁决。

任何证据缺失、摘要不符、计数过期、事件生命周期异常或 manifest 路径集合变化，校验器均以退出码 2 失败关闭。

## 正式报告和缺口

- 人类可读主报告：`docs/OpenClaw-Claude-Agent-SDK能力映射与架构边界.md`
- 机器可读映射：`mapping/capability_mapping.json`
- P0/P1 缺口：`gaps/migration-gap-list.json`
- 目标事件契约：`schemas/runtime-event-envelope.schema.json`

事件 Schema 是 `TARGET_ONLY`，不能作为当前 Runtime 已符合强契约的证据。
