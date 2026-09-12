# Claude Agent SDK Runtime 迁移缺口清单

**Run：** `run_9226059d74a1`  
**节点：** `runtime_probe_harness`  
**总体结论：** `NO_GO`  
**证据截止：** sequence `6015`；events SHA-256 `41171e25f262f44f71aad2273dbac20c556bd807ca95c8ac1ff036aef38ebc40`。

本清单由 `evidence/runtime_probe/evidence-index.json` 自动生成。`PARTIAL` 不等于发布通过，本地探针均为 `acceptance_eligible=false`。

| ID | 优先级 | 状态 | 缺口 | 当前证据依据 |
|---|---|---|---|---|
| CAM-00 | P0 | OPEN | OpenClaw capability baseline and retirement evidence | Mapping artifact exists, but parity, zero traffic, no bypass, single writer and rollback are not proven. |
| CAM-01 | P0 | PARTIAL | Claude Agent SDK runtime identity and session lifecycle | 26 completed-turn bindings verified; explicit SDK session start/continue lifecycle is incomplete. |
| CAM-02 | P0 | OPEN | Five distinct production roles | 5 distinct bound agents are visible, but they are not bound to the five required named roles; role-to-session proof is absent. |
| CAM-03 | P0 | PARTIAL | Tool request, authorization, result and side effect | 979/979 projected groups have four platform phases; raw request/result bytes, independent schema denial and result digests are absent. |
| CAM-04 | P0 | PARTIAL | File delivery and Artifact Registry | 38/38 registered bytes verify; full collect/download lifecycle covers 36 artifacts, not every artifact. |
| CAM-05 | P0 | PARTIAL | Typed public collaboration | 14 public messages across 5 actors are visible, not a five-role production flow. |
| CAM-06 | P0 | OPEN | Independent Judge rejection and re-judgment | Projected Judge/gate event count is 0. |
| CAM-07 | P0 | PARTIAL | Immutable rework attempt causality | 1 attempt.created event has rework_of, but no independent Judge causation is visible. |
| CAM-08 | P0 | PARTIAL | Memory write, commit, new-session read and use | Committed=4; later cross-session commit→retrieve→use proven=False. |
| CAM-09 | P0 | OPEN | Intentional platform pause and resume | Intentional pause/resume event count is 0. |
| CAM-10 | P0 | PARTIAL | Failure recovery and exactly-once reconciliation | Platform interruption/recovery chain exists, but terminal duplicate-side-effect reconciliation and convergence are absent. |
| CAM-11 | P0 | OPEN | Terminal Run reconciliation | Frozen Run status is running. |
| CAM-12 | P0 | OPEN | OpenClaw retirement | No complete entrypoint inventory, zero-traffic window, no silent fallback and retirement rollback evidence. |

## 关闭原则

- 必须使用本次 Run 后续平台事件、SDK Session binding、Artifact Registry 原始字节或独立审计产物关闭；
- 不得用本地子进程事件替代平台 Judge、Memory、暂停或 Worker 恢复事件；
- 五个 distinct actor 计数不能替代产品、架构、工程、质量、独立裁判五个具名角色与独立 Session 的绑定；
- OpenClaw 退役必须补齐全入口、零流量、无旁路、无静默回退、单写者和回滚演练。
