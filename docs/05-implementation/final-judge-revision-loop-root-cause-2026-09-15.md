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
