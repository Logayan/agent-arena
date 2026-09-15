# 最终 Judge 反复 90%→80% 根因分析（2026-09-15）

## 结论

正式 Run `run_bda13e93b2ea` 不是卡在同一次最终裁决。每一次独立 Judge 都已经正常结束并返回机器裁决；最近一次为 sequence `162555`、`REVISE / 88`。平台没有进入 `run.completed`，是因为裁决结果仍为退回，工作流随后重新开放责任节点及其下游。

页面中的 `90%`、`80%` 是工作流节点完成占比，不是 Judge 评分。该工作流共有 10 个节点：只剩最终 Judge 时为 9/10，即 90%；旧路由把最终报告与最终 Judge两个节点重新置为待完成后为 8/10，即 80%。

## 为什么第 8 次 Judge 仍然退回

sequence `162555` 的机器裁决已经承认以下证据成立：Claude Code SDK Bridge 真实运行、228/228 completed-turn Runtime binding、13/13 生产源码 Registry 原字节、六席独立协作闭环、6528/6528 Registry 对象以及 179/179 Manifest/ZIP 字节校验。

仍阻断通过的不是“Claude SDK 没启动”，而是最终发布证据没有形成单一、当前、可机器判定的权威口径：

- 正式报告冻结在 sequence `147903`，没有纳入后续已经产生的新证据；
- machine package authority 仍为 0，`supersedes` 还错误指向普通 `.pyc` 文件；
- QA、owner、architecture 三套测试与缺口分母互相冲突；
- Tool 全量 Schema/SDK/对象账本、Memory completed-turn closure、checkpoint-bound continuation、原生 recovery Attempt、对象级 exactly-once 和十类入口持续观察证据未全部闭合；
- 后端、Bridge、产品单测、Runtime contract、前端 build 在该裁决冻结快照中仍被记录为 BLOCKED；
- 因此还没有 `gate.passed`、`run.converged`、`run.completed`。

## 为什么会重复循环而不是停止

sequence `119020` 将当前 Run 的 `max_revision_rounds` 设为 `0`，语义是可审计的无限返工，来源是“持续 Loop，直到独立 Judge 得出可复核结论”。所以第 6、7、8 次退回不会进入 `revision_exhausted`，而是继续保留历史证据并开启下一轮。

旧执行器还有一个放大循环的问题：Judge 即使指出 Runtime、代码、E2E 或 Artifact authority 的事实缺陷，也只打回 `final_report_and_gap_list`。报告节点只能重新汇总，不能改变底层事实，容易形成稳定的 `90→80→90`。

提交 `b7c338a` 已修复路由：报告级退回会同时补充最近的 `remediation_rerun`，让真实产品源码、测试和证据先发生变化，再重做报告和 Judge。当前 epoch44 已在独立 `product-source` 上执行该整改链，不是继续只改报告。

## 本次额外发现的进度投影缺陷

当前状态中 `remediation_rerun`、`final_report_and_gap_list`、`final_independent_judgement` 三个节点均不是 completed，按 10 个节点计算应为 70%。页面仍显示 80%，原因是用户返工干预应用后，执行器重置了任务状态，但没有立即重算 Run 的 progress；直到下一批节点完成才会刷新。

本次已修改执行器，使 `require_rework` 应用后立刻按当前有效 completed 节点重算进度；页面说明也改为动态展示待完成节点数量和名称，并明确“裁决已结束、当前在返工”和“百分比不是裁判评分”。该代码不会热重启或打断当前正式 Run，将在安全边界加载。

本地验证结果：Runtime 安全合同 `47 passed`，后端全量 `219 passed`，前端 production build `1778 modules transformed`，Python 编译和 `git diff --check` 均通过。首轮禁用 pytest 插件时出现的 3 个异步用例失败已确认是 anyio 插件未加载；恢复项目正常 pytest 配置后全量通过，不计为产品缺陷。

## 当前是否卡住

截至本次核对，Run 为 `running`，当前 Attempt 为 `attempt:run_bda13e93b2ea:remediation_rerun:epoch44:loop2:node1`。sequence `163032` 至 `163037` 持续出现两名角色的 Claude Code SDK Bridge 心跳，并有真实后端测试、源码与证据核验命令执行。因此当前是长整改回合，尚无停滞证据。

后续正式测试暴露了 Windows 深层隔离目录问题：一次后端全量执行报告 `55 failed / 163 passed`，抽样堆栈均落在同一 `WinError 206`/`FileNotFoundError` 长路径根因。`SUBST R:` 不能解决，因为 pytest 和 `PlatformStore` 会调用 `Path.resolve()`，把别名展开回深层 delivery 实路径。sequence `163376` 的 E2E 命令虽为 exit 0，但约定输出目录为空，也不能作为有效 PASS。

已向当前整改节点提交补充干预 `intervention_17e5080d9d3d`：要求使用 Bridge 已保留的系统 `TEMP/TMP` 作为真实短 basetemp，测试完成后再把 JUnit、stdout/stderr、结果、截图和 Manifest 复制回 delivery/evidence 并注册；同时不得把 55 个同源路径错误拆成 55 个产品缺陷，也不得接受无产物的 E2E exit 0。

平台根治同步落到 `ClaudeCodeRuntime.for_run()`：默认仍使用 `<execution_root>/tmp/claude-agents`；仅当运行环境为 Windows 且该路径达到 120 字符时，自动切换到系统临时目录下以 Run ID 和 execution-root SHA-256 前缀隔离的短工作区。也可用 `JIANGHU_CLAUDE_RUN_WORKSPACE_ROOT` 显式配置。该判断不把产品定义为 Windows 优先，只针对当前系统和实际路径长度适配；非 Windows 与短 Windows 路径保持原行为。Runtime/Adapter 定向合同 `32 passed`，包含长路径切换、短路径保持和 Run/Agent/Session 隔离验证；最终后端全量为 `221 passed`，Python 编译与 `git diff --check` 通过。

正式 authoritative 重跑随后只剩 `test_active_database_model_config_is_loaded_without_mutating_database` 一个失败。根因是 baseline 脚本用 `file:{path.as_posix()}?mode=ro` 手工拼 SQLite URI，Windows 短盘符/扩展路径会被 SQLite 解释为无效 authority。宿主实现已改为 `Path.as_uri()` 后再追加 `mode=ro`；baseline 定向测试 `3 passed`。

## 2026-09-15 18:24 新发现：冻结快照一致性判定存在不可能同时满足的条件

sequence `166126` 的整改期独立校验结果为 `core=true`、`coherent=false`、`NO_GO`。原始计数为：公开投影事件 `162751`、声明省略的 private-audit 事件 `91`、投影最大 sequence `162842`、`run-metadata.event_count=162840`。公开事件与声明省略恰好覆盖 sequence `1..162842`，关键事件、6540 个 Artifact 原字节及三阶段生命周期均无缺失或哈希错误。

除 `run-metadata.event_count` 本身落后当前冻结边界 2 个事件外，校验器还有确定性的逻辑错误：它在 `snapshot_coherent = all(invariants.values())` 中同时要求：

- `metadata.event_count == projected_event_count`；
- `metadata.event_count == projected_event_count + declared_omissions`。

只要存在任何合法的私有省略事件，这两个等式就不可能同时成立。因此即使工程测试、Artifact 字节和事件覆盖全部通过，`snapshot_coherent` 仍会固定为 `false`，并把结果降为 `NO_GO`。这属于最终证据校验器的假阻断，是“裁决反复无法结束”的直接放大原因之一，不能通过单纯增加执行时间解决。

正确语义必须由快照契约明确二选一：若 `run-metadata.event_count` 表示源事件总数，则只与 `projected_event_count + declared_omissions` 比较；若表示公开投影数，则只与 `projected_event_count` 比较，并单独记录源事件总数。生成器还必须在同一冻结边界内原子写入 cutoff sequence、源事件总数、公开投影数和省略数，避免抓取期间新增事件造成 metadata 落后。当前正式整改角色正在修改并重跑该校验链，尚未产生新的 Judge 终态。

同一校验器还存在裁决阶段循环依赖：它在最终 Judge 之前执行，却用 `not event_type_counts["run.completed"]` 直接把 `acceptance_decision` 判为 `NO_GO`。平台设计中 `run.completed` 必须由 Judge `ACCEPT` 后才生成，因此该条件等价于要求“先完成 Run，才允许进入能完成 Run 的 Judge”。正确实现必须拆成两个阶段：裁决前只验证输入快照和发布前门禁，成功后返回 `READY_FOR_INDEPENDENT_JUDGE`，并把 `gate.passed/run.converged/run.completed` 标记为 `expected_after_accept`；裁决后的终态验证再要求三类事件完整出现。对应角色定向纠偏为 `intervention_58a6b34a0295`；为确保当前人物回合结束后的协调/集成角色也必须处理，另登记节点级纠偏 `intervention_40d22bc758cd`。

最终结束的硬条件仍是同一 Run 依次产生：`gate.passed`、`run.converged`、`run.completed`。

## 2026-09-15 20:02 实时复核

正式 API 返回 Run 仍为 `running / 80% / 退回缺陷整改与全链路重跑`，但 10 个任务中实际只有前 7 个为 `completed`：`remediation_rerun` 为 `running`，`final_report_and_gap_list` 与 `final_independent_judgement` 为 `pending`。因此当前有效进度应为 `7/10 = 70%`；页面的 80% 是旧服务尚未加载“返工后立即重算进度”的修复，不代表 Judge 分数下降。

当前角色谢临川仍在 epoch44 的 Claude Code SDK Attempt 内运行，sequence 已持续增长至 `167557+`，并持续产生 `agent.action.heartbeat`、命令执行和副作用核验事件，没有静止或 1800 秒超时证据。最新严格生命周期分析文件生成于 `19:56:30`，结果仍为 `CAM 3/13`、`migration=NO_GO`；主要未闭合项包括旧冻结快照计数、缺少原生 `sdk.session.continued`、历史 Schema 失败后仍执行、缺少 Artifact authority、Memory hidden 后又被读取、以及把 Judge/Run 终态错误列为裁决前条件。

三项针对确定性假阻断的纠偏 `intervention_9d8960648635`、`intervention_58a6b34a0295`、`intervention_40d22bc758cd` 截至本次复核仍为 `queued`，尚未在当前长 Attempt 的安全边界应用。因此当前不能直接重新启动最终 Judge；否则旧门禁会继续给出 `NO_GO/REVISE`。需要先让整改 Attempt 结束并应用纠偏，生成新的同边界快照与权威 Artifact，再进入报告和独立 Judge。

## 2026-09-15 20:31 CAM-05 平台修复

主工作区已实现任务级 Artifact authority：当前成功 Attempt 的工作流输出、登记文件、Git Commit 和远端交付回执在 Memory closure 等全部后置核验通过后才原子切换为 `authoritative`；旧权威集合仅改为 `superseded`，不删除历史。平台会逐项发出 `artifact.authoritative`，并以顺序无关 Manifest SHA-256 发出 `artifact.authority.frozen`。应用内 Artifact 详情同时展示 authority 与 supersedes 回执。

本地验证为 Runtime 安全合同 53/53、后端全量 227/227、Artifact 详情和 Judge 返工集成 2/2、Bridge 10/10、前端构建 1778 modules。该实现必须在正式整改 Attempt 到达安全边界后加载，并由新事件证明 CAM-05 闭合；本地绿测不能代替正式 Run 的平台 authority 事件。

## 2026-09-15 22:27 新发现：Playwright 浏览器运行时被误当成交付文件

正式 Run 当前并未进入最终 Judge。数据库任务状态为前 7 个节点 completed，`remediation_rerun` running，最终报告与最终 Judge pending。整改负责人已在 sequence `169762/169763` 完成业务输出，但节点后置流程随后把人物工作区中的 `.playwright-browsers` 当成代码和证据变更处理。

现场目录包含 310 个 Playwright 浏览器运行时文件、约 452,900,609 字节。sequence `169764` 起连续出现这些浏览器二进制和语言包的 `agent.file.created`；数据库已增长至约 1.49 GB，WAL 约 131 MB，8003 `/api/health` 超时，而 Worker PID 8028 仍存活并持续消耗 CPU。这说明节点没有卡在 Claude Code SDK 或 Judge，而是同步逐文件晋升、哈希、Artifact 登记及事件持久化拖住了 API 事件循环。最终 Judge 必须等待整改节点全部后置动作完成，因此尚未获得调度机会。

根因是 `ClaudeCodeRuntime._workspace_snapshot()` 与 `_copy_tree()` 的忽略目录没有包含 `.playwright-browsers`；工程负责人全树晋升后，这批执行基础设施又进入 `recorded_file_changes`。同时 `agent.file.*` 事件原实现逐条同步写库，进一步放大延迟与页面不可用。

修复策略：统一从快照、种子复制、全树晋升和 Artifact 变更中排除 `.playwright-browsers`，但继续保留真实截图、HAR、trace、JUnit、HTML/JSON 报告等 E2E 证据；文件变更事件改为单批异步落库，避免大量合法交付文件阻塞 API。当前 Run 已请求安全暂停，先让旧进程完成已开始的后置事务并持久化 Checkpoint；到达 `paused` 后加载新代码，再从已排队的定向整改干预恢复同一 Run 与 Version。

22:34 使用 `py-spy` 读取 PID 8028 的 Python 栈，确认主事件循环同步阻塞在 `commit_run_changes → git add --all → subprocess.communicate`。实际 Git for Windows 子进程 PID 7936 从 22:27:52 起持续扫描已误晋升的浏览器与历史证据；`subprocess.run(timeout=60)` 只终止了 `cmd/git.exe` 启动器，真正的 `mingw64/bin/git.exe` 成为孤儿并继续持有管道，所以 Python 的超时清理无法返回。为防止 453 MB 浏览器运行时被提交及远端推送，已精确终止该孤儿 Git 子进程；原 Git index 未被替换，现场文件和数据库均保留。平台随后写入 sequence `174117 task.failed` 与 `174118 run.failed`，有效进度按 7/10 正确落为 70%。

宿主修复同时补充：Git for Windows 优先直接调用 `mingw64/bin/git.exe`，使超时可以终止真实进程；默认 Git 命令上限从 60 秒改为可配置的 600 秒；超时包装为 `GitDeliveryError(git_command_timeout:<operation>)`，不再误报为模型请求超时；本地 Commit 全流程移入工作线程，Git 较慢时 8003 API 仍可响应。

失败现场复核到 `product-source` 有 3,780 条工作树变化：仅 6 条为 tracked 修改，其余主要分布于 `evidence` 1,489、`claude-runtime-migration` 975、`x` 546、`deliverables` 307、`t` 242、`artifacts` 20 等生成目录。其根因是负责人完成后调用 `promote_workspace_tree()`，把整个人物 delivery 与产品 checkout 做镜像同步，再由 `git add --all` 无边界暂存。修复后只晋升本 Claude SDK 回合的产品文件变化；截图、HAR、trace、JUnit、报告、ZIP 等仍从人物 delivery 注册为 Run Artifact，但排除于产品源码晋升；Git Commit 只暂存本回合实际晋升的产品路径。这样 Evidence Center 可见性与产品 Git 纯净度不再互相冲突。

本轮宿主修复验证：Runtime/Git/执行安全定向合同 `85 passed`，后端全量 `233 passed`，Claude Agent SDK Bridge `10/10 passed`，前端 production build `1778 modules transformed`，Python 编译与 `git diff --check` 通过。

epoch45 启动后 `git.workspace.ready` 已正确绑定 `origin/master@c033265`，并在 sequence `174360` 首次产生原生 `sdk.session.continued`。同时从人物命令 `pwd` 发现工作区仍位于 Run 深目录：旧选择器只检查 112 字符的 `.../tmp/claude-agents` 基础根，没有计入 Agent ID、`delivery` 以及 pytest/Playwright 后续临时层级，因此仍可能重现 WinError 206。选择器已改为按“最大规范化 Agent ID + delivery”预计路径判断是否切换系统短根；非 Windows 与真正短路径行为保持不变。

## 2026-09-15 23:48 当前 90%→80% 与“最终裁决不能结束”复核

实时 API 对同一正式 Run `run_bda13e93b2ea` 返回 `pause_requested / 70% / 退回缺陷整改与全链路重跑`，事件已增长到 sequence `175908`。10 个节点中当前 7 个 `completed`，`remediation_rerun=running`，`final_report_and_gap_list=pending`，`final_independent_judgement=pending`。最近事件仍有林砚测试启动、谢临川 Bash 完成与副作用核验，说明当前不是 Judge 卡死；Judge 尚未获得调度，平台正在等待当前整改 Attempt 安全排空后执行暂停。

页面此前反复出现的 `90%→80%` 是节点状态投影：最终报告完成后为 9/10；Judge 返回 `REVISE` 后，执行器调用 `_resolve_gate_targets()` 选择返工责任节点，再由 `downstream_from()` 把依赖这些产物的报告与 Judge 一并重置为 pending，当前有效完成节点减少，所以百分比下降。它不是 Judge 的 90 分变成 80 分，也不是历史产物或执行结果丢失。

最终裁决长期不能收敛曾由以下因素叠加造成：

1. 当前 Run 的 `max_revision_rounds=0` 为无界返工；只要 Judge 不 `pass`，平台就不会因轮数自动结束。
2. 旧版本把代码、Runtime、E2E 和 Artifact 权威性缺口只退回报告节点，重写报告无法改变底层事实，形成稳定循环；现已改为路由到 `remediation_rerun`。
3. 旧冻结校验同时要求互斥的事件计数等式，并在 Judge 前要求 Judge 通过后才可能出现的 `run.completed`，形成假阻断和阶段循环依赖；epoch45 已生成同游标算术闭合快照并改为 pre-Judge / post-Judge 两阶段语义。
4. Windows 长路径、Playwright 浏览器运行时误晋升、全树 Git 暂存和同步 Artifact 事件曾拖慢整改后置流程，使 Judge 长时间无法被调度；对应宿主修复已提交，但必须在安全暂停后重启加载并由下一 Attempt 证明。

因此，当前不能通过“继续等待同一个 Judge”解决：正确路径是让 epoch45 当前整改回合安全结束，加载已推送修复，原地恢复同一 Run，重新完成整改、报告和全新独立 Judge。只有同一 Run 按顺序产生 `gate.passed → run.converged → run.completed` 才算最终裁决真正结束。

## 2026-09-16 03:44 epoch46 实时复核

正式 Run `run_bda13e93b2ea` Version 9 当前为 `running / 70% / 退回缺陷整改与全链路重跑`。10 个固定节点中只有前 7 个处于当前权威 `completed` 状态；`remediation_rerun=running`，`final_report_and_gap_list=pending`，`final_independent_judgement=pending`。因此此刻不是最终 Judge 执行后卡住，而是 Judge 尚未获得调度，必须等待整改节点和最终报告依次完成。

监控事件从 sequence `183590` 持续增长到至少 `183652`，两名 Claude Code SDK 角色均继续产生工具完成、测试完成和 `agent.action.heartbeat`，没有静默停滞证据。当前新暴露的直接阻断位于 Windows 上的 Bridge 验证命令：Claude SDK Bash 回合原本传入 `cmd.exe /d /c npm ci --ignore-scripts`，但参数在到达 Python receipt runner 前已被 MSYS 路径转换为 `cmd.exe D:/ C:/ npm ci --ignore-scripts`。命令因此只打开并退出 `cmd.exe`，未执行 npm；权威 receipt 显示 `child_exit_code=0`，但期望的 `server/claude_agent_runtime/node_modules` 不存在，所以有效结果被正确降为 `exit_code=2 / expected_outputs_valid=false`。单纯把 `MSYS2_ARG_CONV_EXCL=*` 放进子进程环境无法修复，因为参数改写发生在启动 Python runner 之前。

随后林砚完成一轮真实后端全量回归，结果为 `241 passed / 1 failed`。唯一失败是 `test_rtc_001_health_and_port_are_available_for_both_adapters[claude_code]`：Claude Runtime health 中 `version=''` 且 `available=false`。该失败与上述 Bridge 依赖未安装属于同一因果链，并非另一个 Judge 缺陷；在 npm 安装和 Bridge 测试形成有效 receipt 前，整改节点不能被标记 completed。

页面历史上的 `90% → 80%` 仍是节点权威状态变化，不是 Judge 分数变化：最终报告完成时为 9/10；Judge 返回 `REVISE` 后，责任节点及依赖其新产物的下游节点被重置为 pending，完成节点数下降。当前定向整改会同时打开整改、报告和 Judge 三个节点，因此有效进度进一步是 7/10，即 70%。

最终裁决不能自动结束的控制面原因是当前 Run 明确配置了 `max_revision_rounds=0`，即无界返工。该策略只保证“不因固定轮数强杀”，并不保证收敛；只要 Judge 仍返回 `REVISE`，平台就会继续重置责任节点和下游。真正结束仍必须先消除验证链中的事实缺口和假阻断，再由同一 Run 依次产生 `gate.passed → run.converged → run.completed`。当前应继续完成 epoch46 的命令启动适配、全量回归和权威证据封存，而不是等待尚未启动的 Judge 或取消无界 Loop 来制造假完成。

后续执行已证明上述 npm/MSYS 启动问题可修复：角色改为直接通过 Windows Node 与 `npm-cli.js` 启动安装/测试，Bridge receipt、后端权威全量回归、真实 `5173 + 8003` Evidence Center E2E、OpenClaw 生产残留扫描、凭据扫描和 `.playwright-browsers` 排除检查均已出现有效 PASS。最终提交阶段又修正 Git 子进程继承 `GIT_*` 覆盖、事件快照元数据契约及相关回归，修复后后端全量、Bridge、前端构建和 E2E 再次通过。

截至 sequence `186555+`，综合检查为内容、Registry、残留、凭据和测试通过，但冻结快照状态为 `PASS_CONTENT_COHERENCE_BLOCKED_NEW_BOUNDARY_ATTESTATION`。这是当前尚未进入 Judge 的准确原因：修复发生在旧快照冻结边界之后，平台必须先完成正式提交、Memory/Git/Artifact authority 后置核验并生成新的权威边界证明。使用旧快照直接裁决会再次产生错误 `REVISE`，所以当前保持 70% 是正确保护，不是进度算法再次卡死。

## 2026-09-16 现场终态复核：当前并非 Judge 卡住，而是最终报告节点被 Bridge 异常中断

实时 API 对正式 Run `run_bda13e93b2ea` Version 9 的返回为：

```text
status=failed
progress=80
stage=execution_failed
remediation_rerun=completed
final_report_and_gap_list=failed
final_independent_judgement=pending
```

因此当前 `80%` 的准确含义是 10 个固定节点中 8 个处于当前有效 `completed` 状态；第 9 个“迁移验收报告与缺口清单封版”失败，第 10 个“最终独立裁决”尚未调度。页面看到的现象不是 Judge 一直运行但无法结束，也不是 Judge 分数从 90 降到 80。

最终报告节点已连续两次以相同结构失败：

```text
epoch46: sequence 188145 task.failed → 188146 run.failed
error_type=PermissionError
diagnostic_id=diag-3a37629329840c3f

epoch47: sequence 188543 task.failed → 188544 run.failed
error_type=OSError
diagnostic_id=diag-52014e2ab3f0bc87
```

两次 Claude SDK 会话均在同一人物回合中并发发起三条 `mcp__jianghu_workspace__bash`。其中两条返回完整 Tool result，第三条只留下 `agent.tool.started / agent.command.started`，没有对应的终态 Tool result，随后 SDK 会话在没有最终 assistant result 的情况下结束，宿主把底层 `PermissionError/OSError` 提升为整个节点失败。

代码核验确认 `server/claude_agent_runtime/bridge.mjs` 的 Bash Tool 当前存在两个宿主级缺口：

1. 同一 `workspaceServer` / SDK Session 的 Bash 调用可以并发执行；Windows 下多个 shell/process 同时启动时会放大句柄、权限和进程创建竞争。
2. `spawn()` 直接写在 Promise executor 内，未用同步 `try/catch` 包裹；如果进程创建同步抛出异常，MCP Tool callback 会 reject，而不是返回一个可审计的 `isError=true` Tool result，进而终止整个 Claude SDK turn。

这也解释了为什么仅靠提示词要求“串行读取证据”仍会复现：模型仍可能一次返回多个 Tool use，可靠约束必须由 Bridge 宿主实现，而不是依赖人物遵守提示词。

当前收敛路径不是延长等待时间，也不是直接重跑 Judge，而是先修复 Bridge：对同一 Session 的 Bash Tool 做串行队列；同步 `spawn` 失败转换为 MCP 错误结果；补充并发顺序、失败后队列可继续、同步 spawn 异常不击穿 SDK turn 的回归测试。修复加载后，应从 `task_764f124e78e1` 原地恢复同一 Run，只重开最终报告和最终 Judge，并继续以同一 Run 出现下列顺序作为唯一完成条件：

```text
gate.passed → run.converged → run.completed
```

## 2026-09-16 Bridge 宿主修复与本地验证

已在 `server/claude_agent_runtime/bridge.mjs` 完成宿主级修复：

- 新增 Session 内串行执行器，所有同一 `workspaceServer` 的 Bash Tool 按提交顺序逐个运行；
- 队列使用成功/失败双分支推进，单条命令失败不会使后续命令永久阻塞；
- 将进程启动封装为可独立验证的 `runSpawnedCommand()`；
- 对同步 `spawn()` 异常进行捕获并返回 `isError=true` 的 MCP Tool result，不再让异常 reject SDK Tool callback 或终止整个人物回合；
- 保持原有超时、进程树终止、凭据隔离、输出上限和命令路径约束不变。

新增 Bridge 回归覆盖：

1. 多个并发提交严格按顺序执行；
2. 前一个 operation reject 后队列仍可继续；
3. 同步 `spawn` 失败返回 MCP 错误结果，而不是 Promise reject。

本地验证结果：

```text
Claude SDK Bridge: 13 passed
Claude Runtime contract: 22 passed
Backend full regression: 234 passed, 1 warning
Frontend production build: 1778 modules transformed, PASS
```

第一次使用系统 Python 启动 pytest 时，测试尚未收集便因全局 `logfire` 与 `opentelemetry` 插件版本冲突失败；改用项目锁定的 `.venv`（pytest 9.1.1）后 Runtime 合同和后端全量均通过。该环境失败不计为产品回归失败，但保留在执行记录中。

下一步是在安全边界加载已提交 Bridge 修复，然后从 `task_764f124e78e1` 原地恢复同一 Run。恢复必须保留前 8 个已完成节点、历史失败 Attempt 和全部 Artifact，只重新执行最终报告与最终独立 Judge。

## 2026-09-16 epoch48：Bridge Tool 修复后发现进程树启动并发的第二层故障

提交 `2d52916` 已推送至 `origin/master`，后端重启后 Runtime health 为：

```text
available=true
runtime=claude_code
mode=agent-sdk-bridge
version=0.3.268
model=gpt-5.6-sol
```

同一 Run 随后从 `task_764f124e78e1` 原地恢复到 execution epoch 48，恢复结果准确保留 8 个已完成节点，只重开最终报告和最终 Judge。epoch48 在 sequence `188643..188718` 启动六名报告参与者，但在产生任何 SDK meta、Tool call 或 Tool result 前，于 sequence `188719 task.failed → 188720 run.failed` 再次以 `OSError / diag-52014e2ab3f0bc87` 终止。

该失败与已修复的“单 Session 内并发 Bash”不同。代码路径证明 `ClaudeCodeRuntime.message()` 的 `asyncio.create_subprocess_exec()` 原先可能直接抛出原生 `OSError`；人物级和节点级重试只捕获 `AgentRuntimeError/LLMRequestError`，因此该异常绕过所有自动重试并直接击穿节点。与此同时，工作流允许最多 5 个成员并发启动 Node + Claude SDK 进程树，在当前 Windows 宿主上放大了瞬时 `CreateProcess` 资源/权限竞争。

第二层宿主修复包括：

- 对 Bridge 进程创建临界区做短时串行化，不限制已成功启动会话的后续执行；
- 将进程启动 `OSError` 包装为 `ClaudeCodeRuntimeError(category=runtime_failure,retryable=true)`，保留 `error_type/errno/winerror` 诊断元数据，从而进入既有人物级和节点级重试；
- 新增 Claude Runtime Session 并发限制：Windows 默认最多 2 个重型 SDK 进程树，可通过 `JIANGHU_CLAUDE_MAX_PARALLEL_SESSIONS` 配置；非 Windows、非 Claude Runtime 和工作流节点并行语义保持原行为；
- `run.started/run.recovered` 事件新增 `max_parallel_runtime_sessions`，使实际宿主并发口径可审计。

验证结果：

```text
Runtime targeted contracts: 78 passed
Backend full regression: 236 passed, 1 warning
Claude SDK Bridge: 13 passed
Frontend production build: 1778 modules transformed, PASS
```

下一次恢复必须在加载第二层宿主修复后执行，并确认 `run.recovered` 明确记录 `max_parallel_runtime_sessions=2`。若再次发生进程启动失败，应出现 `agent.action.retrying/failed` 及 Claude Runtime 诊断元数据，而不能再以原生 `OSError` 直接从 `agent.turn.started` 跳到 `task.failed`。

## 2026-09-16 epoch49：恢复历史查询触发 SQLite 临时磁盘耗尽

第二层修复提交 `08cd98d` 推送并加载后，epoch49 的 `run.recovered` 已明确记录：

```text
execution_epoch=49
max_parallel_agents=5
max_parallel_runtime_sessions=2
runtime=claude_code
runtime_mode=agent-sdk-bridge
completed_node_keys=8
interrupted_node_keys=2
```

该回合在启动最终报告前，于 sequence `188804 run.failed` 以 `OperationalError / diag-bf6f6c1c087e2b00` 终止。现场最后成功事件为历史 Runtime Artifact 下载复算，下一步正好是 `_compact_tool_recovery_history()`。

对生产数据库执行原查询已直接复现真实错误：

```text
sqlite3.OperationalError: database or disk is full
```

原实现对 18 万+事件使用：

```sql
SELECT *
FROM events INDEXED BY idx_events_artifact_lookup
WHERE run_id=? AND organization_id=? AND type IN (...)
ORDER BY sequence
```

被强制使用的索引按 `run_id,type,created_at` 排列，不能满足跨多个 type 的 `ORDER BY sequence`。SQLite 因此把包含大 Tool payload 的候选行写入系统临时排序文件；现场系统盘只剩约 `0.57 GB`，最终触发临时磁盘耗尽。Run 数据库本身位于 D 盘，错误不是 Registry 或事件损坏。

修复将按类型事件读取改为基于持久 `sequence` 的 keyset 游标：

```sql
SELECT * FROM events
WHERE run_id=? AND organization_id=? AND type IN (...)
  AND sequence>?
ORDER BY sequence
LIMIT ?
```

每批完成后以最后一个 sequence 继续，不再进行全量临时排序，同时保持事件顺序、无重复、无遗漏和原 payload 可审计。新增测试覆盖 250 条交错事件、两个真实批次 `[100,25]` 及完整 sequence 顺序。

验证结果：定向 Runtime 安全合同 `56 passed`；后端全量 `237 passed, 1 warning`。下一次恢复应越过历史 Tool 恢复扫描并进入最终报告人物回合。

## 2026-09-16 epoch50：跨卷证据镜像耗尽系统盘

提交 `08d13cb` 加载后，epoch50 已成功完成历史 Tool 恢复扫描、`duplicate_side_effect_count=0` 和原生 `sdk.session.continued`，证明 keyset 修复有效。最终报告随后进入 running，但在人物 SDK meta/Tool 事件之前，于 sequence `188966 task.failed → 188967 run.failed` 再次出现原生 `OSError`。

现场目录核验确认，Windows 长路径适配此前把短 workspace 放在：

```text
C:\Users\User\AppData\Local\Temp\jianghu-claude-agents\
```

而 Run execution root、冻结快照和 Artifact 原字节位于 D 盘。`_mirror_evidence_bundle()` 优先使用硬链接，但 Windows 硬链接不能跨卷，因此自动退化为 `shutil.copy2()`。当前 Run 的 C 盘临时 workspace 逻辑文件约 `65,436 MB`，其中绝大多数是各人物 `delivery/.jianghu-platform-evidence` 的重复镜像；C 盘现场只剩约 `0.57 GB`。这解释了 OSError 发生在人物准备阶段、尚无 SDK meta 或 Tool 事件。

修复内容：

- 当 Windows 深路径需要短 workspace 且系统 TEMP 与 execution root 不同卷时，默认选择 execution root 同卷的短根，例如 `D:\.jianghu-claude-agents`；
- 同卷后 evidence bundle 和 materialized Artifact 继续使用硬链接，不再复制十几 GB 原字节；
- 显式配置 `JIANGHU_CLAUDE_RUN_WORKSPACE_ROOT` 或测试传入的 temporary root 仍保持最高优先级；
- 非 Windows 和无需短路径的 Windows execution root 行为不变；
- seed copy、evidence mirror、前后 workspace snapshot 的 `OSError` 均包装为可重试 `ClaudeCodeRuntimeError`，并在安全诊断元数据中公开 `phase/error_type/errno/winerror`，不再以 `runtime=unknown` 绕过自动重试。

定向合同 `81 passed`，后端全量 `239 passed, 1 warning`。尝试删除 C 盘重复镜像时被当前执行策略阻止，现场未删除任何文件；后续收敛不依赖删除，而依赖新同卷根不再产生跨卷副本。权威证据源、事件数据库、Registry 和正式 Artifact 始终保留在 D 盘。
