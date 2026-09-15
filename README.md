# OpenClaw—Claude Agent SDK Runtime 能力映射交付

本目录是 Run `run_6940048dd30f`、Attempt `attempt:run_6940048dd30f:openclaw_baseline_mapping:epoch1:loop1:node1` 的正式合议工程交付根目录。

## 正式结论

```text
mapping_delivery=CONDITIONAL_PASS_EVIDENCE_BOUND_MAPPING
CLAUDE_AGENT_SDK_FULL_RUNTIME_MIGRATION=NO_GO
OPENCLAW_RETIREMENT=NOT_APPROVED
OPEN_GAPS=13
P0_OPEN=11
P1_OPEN=2
```

- 94 条公开事件的 sequence 连续、event ID/source hash 唯一，92/92 critical 完整对象对应；但 `run-metadata.event_count=93` 与投影 94 行存在未关闭的跨文件原子性偏斜。
- 13 份已登记生产源码/部署输入的原始字节和 `created → collected → download.verified` 生命周期均通过；这不代表当前节点候选已获得 Artifact ID。
- 约 16.218 秒内十入口均路由 `claude_code / agent-sdk-bridge`，OpenClaw 请求失败关闭；这不是长期生产零流量证明。
- SDK 依赖精确锁定 `@anthropic-ai/claude-agent-sdk@0.3.268`，但冻结点 completed turn、SDK Session binding 与真实 Tool 生命周期均为 0。
- 两位参与者两轮四条公开消息已纳入内容级综合；它们不在 sequence 94 冻结投影内，因此协作 Runtime 事件级验收仍阻塞。
- 历史 OpenClaw Adapter/契约测试原始字节缺失；Judge、Memory、暂停、故障恢复和 Run 终态均未闭环。

## 主要文件

- `docs/OpenClaw-Claude-Agent-SDK-Runtime能力映射与架构边界.md`：正式报告。
- `docs/01_系统架构视角隔离盘点.md`：系统架构隔离贡献。
- `docs/02_运行保障视角隔离盘点.md`：运行保障隔离贡献。
- `mapping/capability-mapping.json`：机器可读能力映射。
- `gaps/迁移缺口清单.md`、`gaps/migration-gaps.json`：统一缺口真相源。
- `collaboration/public-communication-record.json`：两轮公开消息与综合分类。
- `collaboration/submission-review.json`：两份 manifest 共 59 个路径的逐项采用/拒绝决定。
- `evidence/evidence-index.json`、`evidence/verification-receipt.json`：sequence、Artifact、路径与摘要索引。
- `schemas/runtime-event-envelope.schema.json`、`schemas/runtime-capability-map.schema.json`：机器契约。
- `src/verify_mapping.py`、`tests/test_verify_mapping.py`：可运行验证器与自动化测试。
- `artifacts/sha256-manifest.json`：self-excluding 最终摘要清单。

## 构建与校验

所有命令必须从本 `delivery/` 根目录执行：

```bash
python -m py_compile src/verify_mapping.py tests/test_verify_mapping.py
python -m unittest discover -s tests -v
python src/verify_mapping.py --write-receipt
python src/verify_mapping.py --write-manifest
python src/verify_mapping.py --check-manifest
python src/verify_mapping.py
```

验证器只读取本目录内 `.jianghu-platform-evidence` 冻结证据，不读取 Provider 凭据、环境变量、私有会话或私有 Memory，也不依赖父目录。
