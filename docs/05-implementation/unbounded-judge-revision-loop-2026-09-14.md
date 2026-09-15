# 最终 Judge 无界返工 Loop 与原 Run 恢复

日期：2026-09-14
目标 Run：`run_bda13e93b2ea`
Run Family：`run_0886dd109c15`
Version：9

## 现场问题

最终独立 Judge 已完成第 6 次真实裁决并输出 `REVISE / NO_GO`。全部裁决文件、验证脚本和 Artifact 生命周期证据均已登记，但执行器把 `max_revision_rounds` 强制夹在 `1..6`，随后于 sequence `119019` 写入 `run.revision_exhausted`。这不是 Claude Code SDK 卡住，也不是模型请求未返回，而是平台控制面主动触发了硬上限。

该行为与发起人的持续 Loop 要求冲突，也不适合可能运行数天的生产任务：只要 Agent 仍有心跳、工具事件或文件进展，平台就应继续执行；Judge 的真实退回应形成下一轮可审计整改，而不是被固定轮数截断。

## 决策

- `max_revision_rounds` 缺失时保持产品默认值 `3`；
- `max_revision_rounds > 0` 表示有界返工，超过该值才进入 `revision_exhausted`；
- `max_revision_rounds = 0` 是明确、机器可读、可审计的无界 Loop；
- 正数不再被静默夹到 6，配置值按原值执行；
- 修改只作用于当前 Run 的不可变 `workflow.execution_policy.amended` 事件，不创建新 Run 或 Workflow Version；
- 每轮 Judge、返工、Attempt、文件和失败证据继续追加，禁止覆盖历史。

## 实现

- `server/app/platform_executor.py`
  - 新增 `_normalized_max_revision_rounds()`；
  - 新增 `_revision_limit_exhausted()`；
  - 只有上限大于 0 时才判断返工耗尽；
  - Run-local amendment 保留显式 0 和大于 6 的正数。
- `server/app/main.py`
  - 新增 `POST /api/platform/runs/{run_id}/execution-policy`；
  - 请求必须声明 `node_key`、`max_revision_rounds` 和原因；
  - 目标节点必须属于当前 Run；
  - 返回 `bounded/unbounded` 机器语义并写入不可变审计事件。
- `server/tests/runtime_contract/test_runtime_execution_safety.py`
  - 覆盖 0 在第 6、600 轮均不耗尽；
  - 覆盖正数 12 不再被夹到 6；
  - 覆盖缺失/非法配置回退默认 3。
- `server/tests/test_api.py`
  - 覆盖终态 Run 对指定节点写入无界策略事件。

## 正式应用记录

1. 在 `revision_exhausted` 安全终态受控重启 8003，加载新执行器；Run ID、Version 和 4,189 份既有 Artifact 未改变。
2. sequence `119020`：`workflow.execution_policy.amended`
   - `node_key=final_report_and_gap_list`
   - `task_id=task_764f124e78e1`
   - `max_revision_rounds=0`
   - `revision_policy_mode=unbounded`
3. sequence `119021`：`run.recovery_requested`
   - 来源终态 sequence `119019`
   - 原地恢复节点：`final_report_and_gap_list`、`final_independent_judgement`
   - 其余 8 个已完成节点保持不变。
4. Runtime readiness 返回：
   - `runtime=claude_code`
   - `model=gpt-5.6-sol`
   - `run_version=9`
5. sequence `119201` 后已出现新的 `agent.turn.started`、Bash Schema 校验、授权、工具调用、命令完成、副作用核验和心跳，证明恢复进入真实 Claude Agent SDK 回合。

## 已验证

- 执行安全合同：38 passed；
- 无界策略与恢复 API 影响集：5 passed；
- Python 编译：通过；
- `git diff --check`：通过，仅有 Windows LF/CRLF 提示。

## 后续验收条件

无界 Loop 只消除人为轮数终止，不代表迁移已经通过。最终完成仍必须获得新的独立 Judge 结论，并由真实事件证明 `gate.accepted`、`run.converged`、`run.completed`；若 Judge 再次 `REVISE`，平台必须按本策略继续回到责任节点并保留新一轮全部证据。

本次恢复还暴露了长 Run 启动性能问题：119,000+ 条事件的公开证据快照约生成 279MB `events.ndjson` 和 200MB `critical-events.json`，同步取证期间 API 会短暂变慢。它不影响证据完整性，但必须在安全终态后优化为流式/增量生成，避免无界 Loop 的每轮内存和启动时间随历史线性放大。

## 2026-09-15 13:40 最终 Judge 90% 停留与回退根因复核

当前正式 Run 仍为 `run_bda13e93b2ea` Version 9。工作流固定 10 个节点：最终报告完成后为 9/10，即 90%；独立 Judge 返回 `REVISE` 时，执行器按裁决目标把 `final_report_and_gap_list` 与其下游 `final_independent_judgement` 同时重置为 pending，因此变为 8/10，即 80%。这属于返工状态计算，不是百分比随机倒退，但页面后续应明确展示“裁判退回，进入第 N 轮返工”。

本轮 `final_independent_judgement` 于 sequence `161656` 启动后，直到 sequence `161657` 前约 10 分钟没有 Claude SDK Session、网络请求、工具事件或模型进度。现场代码与磁盘计量确认：Judge 派发前的 `_code_manifest()` 把候选目录内平台生成的 `.jianghu-platform-evidence` 一并作为候选代码做 SHA-256；该目录已有 6,639 个文件、约 17.77GB，且拒绝写入探针连续生成 before/after 两份 Manifest，导致真正模型裁决前读取约 35GB 数据。sequence `161657` 出现后证明这不是模型卡住，而是本地候选清单扫描完成。

修复将 `.jianghu-platform-evidence` 从候选代码 Manifest 中排除，并在目录遍历时直接剪枝，避免继续遍历或读取平台证据；候选源码和正式交付文件仍照常逐字节计算 SHA-256。新增执行安全合同确保证据树不进入候选清单。该修改只写入工作区源码，当前 8003 进程未热加载，须在 Run 安全边界受控重启后才会作用于下一轮 Judge。

最终裁决尚不能通过的业务阻塞与该性能问题不同：epoch42 的统一验收分母仍为 `TOTAL=60 / PASS=17 / FAIL=23 / BLOCKED=20`，CAM 为 `0/13`。当前 Run 的候选 `code/` 不是实际产品源码仓库，缺少 `server/`、`client/` 和真实 Bridge 产品测试入口，也没有 Run Git delivery/remote 绑定；独立 Judge 因而只能把产品级验证保留为 BLOCKED，并继续给出诚实的 `REVISE / NO_GO`。无界 Loop 能保证不断返工，但不能把缺失的产品源码权限和测试证据自动变成通过。

## 2026-09-15 14:50 90%→80% 循环与最终裁决不收敛诊断

实时复核确认，当前 Judge 不是进程死锁。sequence `162395` 已完成最新一次 `verify_current_snapshot.py`，退出码为 0，并重新生成 `verification-result.json`；结果仍为 `decision=REVISE / migration=NO_GO`。Claude Code SDK Bridge 心跳持续写入，当前唯一正式事件会话为 `claude_sdk_session_id=4ccb7dab-7608-4b3b-bc77-8ccdf358a311`。

本次不收敛由四层原因叠加：

1. 进度是“当前仍有效的完成节点比例”，不是累计完成度。最终 Judge 开始时是 9/10，即 90%；Judge 退回后，`_resolve_gate_targets()` 默认选择直接上游 `final_report_and_gap_list`，`downstream_from()` 又把 Judge 自身纳入受影响集合，两个节点一起从 completed 移到 pending，故回到 8/10，即 80%。报告再次封版后回到 90%，形成可重复振荡。
2. 当前正式证据本身明确不满足通过条件：`TOTAL=60 / PASS=17 / FAIL=23 / BLOCKED=20`、`OPEN_GAPS=22`、`P0=18`、`P1=4`、`CAM=0/13`、`UNIQUE_PACKAGE_AUTHORITY=false`、`CURRENT_PACKAGE_ARTIFACT_ID=ABSENT`。因此 Judge 返回 REVISE 是符合证据的，不是误判。
3. 返工目标层级错误。决定性缺口属于真实产品源码 checkout、产品测试入口、Runtime/Bridge/E2E、Artifact authority 和恢复闭环；但最终 Judge 默认只退回“报告封版”节点。该节点只能重新整理同一批证据，不能补齐产品实现和真实测试，所以新报告仍是 NO_GO，下一轮 Judge 仍会 REVISE。
4. 当前 Run 已启用 `max_revision_rounds=0` 无界 Loop。它消除了固定轮数中断，也同时取消了“相同缺口连续出现时停止循环”的收敛保护。只要 Judge 不 ACCEPT，执行器就会永久执行 90%→80%→90%。去掉执行时间限制不能解决该问题，只会让错误目标上的循环运行更久。

当前 Judge 还有一个回合级效率问题：其验证脚本把 `decision` 明确写为 `REVISE`，并反复读取数百 MB 事件投影、核验约 9.16GB 已物化 Artifact、编辑验证器后重跑。退出码 0 只表示“NO_GO 证据验证成功”，不表示“验收通过”。平台仍须等待 SDK 回合输出正式裁决后才会生成 `gate.rejected` 并回退到 80%。

结论：当前现象的主因不是时间上限，也不是 Claude Code SDK 网络阻塞，而是“无界重试 + 错误返工目标 + 通过条件客观未满足 + Judge 缺少同结论快速收卷约束”。后续修复必须让裁决缺口路由到能够改变事实的整改节点，并增加相同 blocker 指纹的无进展检测；否则进度百分比和裁决结果都会持续振荡。

## 2026-09-15 15:20 事实整改路由与真实产品源码接入

sequence `162555` 已形成第 8 次正式 `gate.rejected`。裁决为 `REVISE / 88`，并确认 Claude Runtime binding、当前六席协作和 179/179 Manifest 字节精确等旧缺口已经改善；剩余关键缺口仍包括完整产品命令、Tool/Memory/Recovery 严格闭环、唯一 package authority 和终态事件。旧执行器仍只选择 `target_node_keys=[final_report_and_gap_list]`，因此 sequence `162556` 继续产生报告级返工循环。

本轮实现以下控制面整改：

- 最终 Judge Prompt 不再只暴露直接上游报告节点，而是提供全部传递上游责任节点及节点目的；
- 对涉及源码、实现、Runtime、Bridge、E2E、真实产品测试、恢复或 Artifact authority 的退回，明确禁止只选择报告节点；
- `_resolve_gate_targets()` 只接受合法上游目标，并在报告级目标之外自动补充最近的 `remediation/rework/rerun/整改/返工/修复/重跑` 节点；
- 当前工作流再次 REVISE 时将回到 `remediation_rerun`，再依赖传播到报告和 Judge，而不是只重复封版报告。

Run Git 绑定此前只用于最终 Push/MR，不会把远端产品源码放入人物可见工作区。新增 `ensure_run_source_checkout()`：

- 在 Run 根目录建立独立 `product-source/`；
- 从已冻结的 `repository_url + target_branch` 拉取真实产品源码；
- 使用 Run 专属分支，保留目标分支 commit 和远端身份；
- 工程人物、Judge、代码晋升、Git Commit 与远端交付统一使用该源码 checkout；
- 历史 `code/` 审计仓库、旧 Artifact 与证据快照保持原样，不被覆盖；
- 已有 dirty/diverged checkout 不执行 reset 或覆盖，避免恢复时丢失 Agent 变更。

正式 Git 配置探针成功拉取 `origin/master@6b9f95da5edaa07a918fc5859b45dc6c3a7e365a`，并确认 `client/`、`server/` 与 `server/claude_agent_runtime/bridge.mjs` 均存在。

长 Run 覆盖索引已在 1.44GB 正式 SQLite 上建成：

- `events` 计数：约 `60.37s → 0.063s`；
- 最近 100 事件：`0.009s`；
- 6,537 个 Artifact 查询：`0.136s`；
- 完整 Run 详情接口：约 `65.77s → 6.264s`。

索引首次在线创建期间持有 SQLite 写锁，下一轮事件写入在 30 秒 busy timeout 后产生 sequence `162558 run.failed / OperationalError`。该中断已保留为正式失败证据，Run 当前处于 `failed / 80%` 安全恢复边界；索引现已完整存在，后续启动不会重复执行大表构建。

代码验证结果：

```text
事实整改路由与 Git source checkout 合同：53 passed
server/tests：218 passed in 311.96s
Claude Agent SDK Bridge：10/10 passed
frontend production build：1778 modules passed
生产 Runtime source attestation：passed，blocking_findings=[]
git diff --check：passed（仅 Windows LF/CRLF 提示）
```
