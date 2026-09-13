# Agent 审计自适应超时与预算恢复（2026-09-12）

## 现场判断

真实 Run `run_9226059d74a1` 停留在 `independent_quality_audit`、进度 50%。数据库证据表明这不是进程卡死：两名审计人物的首轮回合在 1800 秒边界产生 `agent.action.retrying`（sequence 19551、19552），第二轮随后继续产生 Read、Edit、Bash 和测试事件；在受控停止前最后一项测试仍于 22:49:58 完成。

根因是平台此前对人物级重试和节点级重试始终复用同一个 `JIANGHU_AGENT_TIMEOUT_SECONDS`。当全面审计确实需要超过 1800 秒时，第二次尝试仍会在同一墙钟边界中断，重复消耗但没有增加完成机会。

## 决策

- 首次人物回合继续使用基础时长；普通纯文本人物默认 600 秒，实际拥有 Runtime 工具的工程、审计和 Judge 人物默认 1800 秒，避免重型审计误落入短文本档。
- 只有错误分类为 `timeout` 时，下一次人物级或节点级自动重试才提高时长；网络、鉴权、配置或无效输出不会触发时长膨胀。
- 默认递增倍数为 2，默认单回合上限为 14400 秒；可通过 `JIANGHU_AGENT_TIMEOUT_RETRY_MULTIPLIER` 和 `JIANGHU_AGENT_TIMEOUT_MAX_SECONDS` 收紧，代码硬上限同为 14400 秒。这样两次人物尝试乘以两次节点尝试均可消费新的超时档位，而不会在重试尚未结束时提前封顶。
- 总 Run 预算继续作为独立硬边界，暂停等待时间不计入活动预算；单人物时长增加不能绕过总预算。
- `agent.action.retrying/failed` 事件记录本次时长、下次时长、递增层级及是否扩容，便于页面和证据包复核。
- 人物级重试已经消耗的超时层级会继续传递给节点级重试，避免出现 `1800 → 3600 → 3600` 的重复档位；上限高于 3600 秒时会按 `1800 → 3600 → 7200` 连续推进，到达配置上限后才保持不变。

目标部署参数为基础 1800 秒、重试上限 14400 秒、倍数 2。完整自动重试链依次为 `1800 → 3600 → 7200 → 14400`；只有到达最后一个配置档位后才保持上限。当前已启动的第 9 版 Worker 仍继承启动时的 3600 秒旧上限，不能在进程内热改；必须在安全恢复边界重启后加载目标上限，且不能为此丢弃正在形成的审计产物。

## 关联缺陷与修复

恢复过程中原 Run 达到 180 分钟总预算，产生 `run.budget_exhausted`。此前的错误公开投影把内部 `budget_exhausted:run_time_limit` 替换为友好文案，但延时接口仍依赖原始错误字符串，导致可恢复的时间预算无法识别。

修复后：

- 新预算事件使用安全机器字段 `budget_kind=run_time_limit`，不需要向浏览器暴露内部异常字符串；
- 公开错误使用 `run_time_budget_exhausted` 和可行动说明；
- 对已存在且缺少 `budget_kind` 的历史事件，以事件时间线计算的活动时长与 Workflow 有效预算做兼容判定；
- `run.time_extended` 只记录安全来源 `run_time_limit`。

## 修改文件

- `server/app/platform_executor.py`：超时递增、重试审计字段、预算类型事件。
- `server/app/platform_store.py`：安全预算类型识别与历史友好事件兼容恢复。
- `server/app/agent_runtime.py`：Run 时间/Token 预算的友好公开错误。
- `server/tests/runtime_contract/test_runtime_execution_safety.py`：基础、倍增和上限合同测试。
- `server/tests/runtime_contract/test_agent_runtime_port.py`：预算公开错误合同测试。
- `server/tests/test_api.py`：真实传参递增、延时恢复和历史兼容测试。

## 真实前端并发读取修复

恢复后刷新 `http://127.0.0.1:5173/?realm=org_jianghu`，页面最终加载了真实委托、组织和 Run，但一度提示“知识图谱暂时不可用”。后端堆栈证明 `/api/platform/organizations/org_jianghu/knowledge-graph` 在审计事件高频写入期间触发 `sqlite3.OperationalError: database is locked`。

直接原因不是知识图谱查询本身，而是 `list_organizations()` 每次读取都重复执行一条历史名称迁移 UPDATE。该迁移已在数据库初始化流程执行，放在 GET 读取路径既无必要，也会把知识图谱只读请求升级为写事务，与 Runtime 事件写入竞争。

现已移除读取路径中的 UPDATE，`list_organizations()` 恢复为纯 SELECT；新增测试在另一个连接持有 `BEGIN IMMEDIATE` 写事务时读取组织列表，证明读取不会再申请写锁。当前运行后端将在审计到达安全边界后重启加载该修复，再执行浏览器复验。

## 恢复 Worker 单写租约

现场清理多个历史 Uvicorn 进程时进一步发现：Uvicorn 在真正绑定 8003 端口之前会先执行 FastAPI startup。两个竞争进程因此可能同时看到 `running` Run 并启动恢复；端口最终只有一个监听者，但两套执行器已经进入同一 Run，旧代码宣称存在 worker lease，实际上只写审计事件，没有真正互斥。竞争写入产生的 SQLite `IntegrityError` 还会被通用异常路径错误地写成 `run.failed`。

现已在 `execute_platform_run()` 的任何 Run、Task 和事件写入之前取得进程生命周期租约：

- SQLite 使用数据库旁的操作系统文件锁；同机竞争进程不能同时进入同一 Run，进程退出或崩溃后锁由操作系统自动释放；
- PostgreSQL 使用专用连接持有 `pg_try_advisory_lock`，连接断开时自动释放；
- 未取得租约的竞争实例直接退出，不修改 Run 状态，也不生成伪失败；
- 租约覆盖整次执行，并在成功、失败、取消或异常路径统一释放。

本地合同测试证明同一 Run 同时只能获得一个租约，释放后恢复 Worker 可以立即接管。该修复与自适应超时独立：租约负责“只有一个 Worker”，超时层级负责“同一个未完成回合的下一次重试更长”。

## 验证与真实恢复

定向回归结果：

- 自适应人物超时与实际 Runtime 参数：2 passed；
- 自适应超时、预算公开错误及延时 API：6 passed；
- 历史友好预算事件兼容：3 passed。
- Runtime Contract 全套：63 passed；
- 后端全量：126 passed；
- Claude Agent SDK Bridge：6/6 passed；
- 前端生产构建：通过，1777 modules；
- Python compile：通过；
- `git diff --check`：通过，仅有 Windows 行尾提示。
- 组织列表并发只读回归：1 passed。

用户进一步确认“未完成时，下次重试应增加时长，不能一直卡在 1800 秒”后，补充修复了人物级最终超时向节点级重试传递超时层级的边界，并增加真实 Worker 单写租约。定向验证更新为：Runtime 执行安全合同 21 passed，真实执行器重试与恢复场景 2 passed；其中人物重试测试直接验证本次参数为 1800 秒、下一次为 3600 秒。

加入 Run 家族活跃版本选择回归后，后端最新全量结果为 133 passed。真实前端已人工切换到第 9 版确认 2 名审计人物持续执行，页面没有展示内部 Provider Trace；列表选择修复将在当前节点到达安全重启边界后加载。

真实 Run 恢复链：

- `run.pause_requested`（19633）与 `run.checkpoint.persisted`（19637）已落盘；
- 受控停止产生 `run.interrupted`（20004），原事件、产物和测试回执未覆盖；
- 延时接口产生 `run.time_extended`（20017），本次增加 120 分钟，有效总时限变为 480 分钟，上限 720 分钟；
- 新后端产生 `run.recovered`（20018）、`agent.runtime.recovered`（20019），确认 `runtime=claude_code`、`mode=agent-sdk-bridge`、模型 `gpt-5.6-sol`；
- 新执行 epoch 10 已重新产生 `task.started`、`agent.action.started`、`agent.turn.started`，Claude SDK Bridge 子进程已启动。

迁移验收仍未结束。必须继续获得最终 `gate.passed` 与 `run.completed`，并完成全量回归、浏览器 E2E 和生产残留扫描后才能给出完成结论。

## 2026-09-13 连续升档复核

最终采用“未完成且错误分类为 timeout，才消费下一时长档位”的状态机。当前配置的四次自动执行机会依次为 `1800 → 3600 → 7200 → 14400` 秒；人物级最后一次超时会把已经消费的档位传给节点级重试，因此不会回落或重复卡在 1800 秒。网络、鉴权、配置、无效输出和普通 Runtime 异常保持原时长，避免用延时掩盖不可恢复故障。

真实第 9 版 Run 已出现 `1800 → 3600` 的超时扩容事件，3600 秒回合随后成功；历史非超时底座异常仍保持 `1800 → 1800`。代码回归进一步用前三次主动抛出 timeout、第四次成功的 Runtime 替身验证完整 `1800 → 3600 → 7200 → 14400` 传参和事件载荷。

本轮同时修复并验证：非工程人物隔离 delivery 文件注册为不可变 Artifact、恢复探针不消费不支持探针的兼容 Runtime 回合、文件注册与 Git 重试配置复制边界。最新结果为后端及 Runtime 合同 `136 passed`、Claude Agent SDK Bridge `6/6 passed`、前端生产构建通过（1777 modules）、Python compile 通过。真实 Run 仍在受控 `pause_requested` 边界内完成已放行回合，未强杀 Worker、未创建新 Run 版本。

随后真实最终报告综合回合在事件 sequence 11312 命中 1800 秒时限，载荷明确给出 `next_timeout_seconds=3600` 与 `timeout_extended=true`；3600 秒重试继续使用同一节点上下文完成交付，并在 sequence 11705 到达有效 paused 边界。这证明扩时逻辑不是仅存在于单元测试，而是已在当前产品 Run 中真实生效。

安全重启后，当前部署已加载基础 1800 秒、上限 14400 秒、倍数 2 的完整配置。恢复链同时完成 OpenClaw 零流量、无双写、Runtime 回滚、lease revoke、stale-writer deny、Tool 终态对账、失败 Tool 逐项处置和 Claude SDK Session continuation 实测；Run 保持第 9 版继续执行。

## 2026-09-13 09:06 同版本预算续跑与未完成判定

用户再次明确：只有回合尚未完成且失败类别为 `timeout` 时，对应的下一次自动重试才增加墙钟时长，不能每次都重新卡在 1800 秒。当前生产逻辑与该决策一致：人物级重试和节点级重试共享连续档位 `1800 → 3600 → 7200 → 14400`；已完成人物或节点不重跑，网络、鉴权、配置和普通 Runtime 错误不消费更长档位。

本轮还区分了两个互不替代的边界：

- 单个 Claude SDK 回合超时：由执行器自动提高下一次重试时长；
- Run 活动总预算耗尽：保留原 Run、版本、事件和 Artifact，通过事件化预算扩展继续未完成节点，不能把总预算误当成 1800 秒 Agent 超时。

真实第 9 版 `run_bda13e93b2ea` 在 sequence 17396 达到 420 分钟有效总预算后，使用同一 Run 增加 120 分钟，sequence 17397 写入 `run.time_extended`，有效预算变为 540 分钟、部署上限仍为 720 分钟。续跑后 sequence 从 17396 增长到至少 17633，`final_report_and_gap_list` 继续产生 Claude Code SDK 的工具 Schema、授权、Read、Bash、命令完成和副作用核验事件；8 个已完成节点保持 completed，最终 Judge 保持 pending。这证明现场是在继续执行，不是固定卡死在 1800 秒，也没有创建新版本或覆盖既有证据。

## 2026-09-13 11:00 最后一轮退回前的安全边界整改

第四轮独立 Judge 对当前证据作出 `revise`，评分 77；这不是执行器卡死，而是机器证据仍有结构性缺口。为避免在第 3/3 次返工后直接进入 `revision_exhausted`，对同一第 9 版 Run 发出节点边界暂停请求。sequence 21615 已登记 `run.checkpoint.persisted`；暂停等待期间 sequence 持续增长到 22596，三位已放行成员仍在执行 Read、Edit、Write、Bash 和测试，证明当前行为是“自然排空”，不是 1800 秒固定卡死，也没有强杀 Agent。

本次代码整改保持自适应超时语义不变，并补齐 Judge 指出的证据合同：

- 公开事件投影加入 Runtime 稳定入口、业务调用、OpenClaw/Claude writer/双写/静默回退计数、Tool Schema 与摘要哈希、失败 disposition、canonical/superseded 终态、Memory 前后版本和 Claude SDK continuation Session ID；
- Runtime 路由新增 `retry` 入口，所有入口形成稳定 `entrypoint_id` 与本 Run/epoch 唯一 `business_invocation_id`；
- 返工 Attempt 的 `rework_of_run_id` 改为被引用 Attempt 实际所属 Run，同 Run 返工不再错误指向父 Run；
- stale-writer deny 使用被撤销的旧 worker/lease 身份，并显式记录当前接管者；
- 多人协作增加 contribution seal、pre-reveal deny、reveal authorization、正式 decision 和 thread freeze 事件；
- 新 Artifact 版本形成平台原生 `artifact.superseded` 关系；
- 生产 `agent-sdk-bridge` 在 Memory commit 后使用全新 Claude SDK Session 执行真实 retrieve/use 闭环；测试替身不额外消费模型回合；
- 允许通过不可变 `workflow.execution_policy.amended` 事件对当前 Run 做执行期成员和返工上限修订，不创建新 Workflow/Run 版本；
- 后端仅在存在显式 `run.restart.requested` 时，于 paused 边界重启后记录真实 `run.interrupted` 与接管回执，不污染其他暂停 Run。

当前验证：Runtime 执行安全合同 29 passed；受影响的团队合议、暂停边界、Judge 返工、恢复和四档超时真实传参场景 7 passed；后端全量 147 passed；Claude Agent SDK Bridge 6/6；前端生产构建通过；Python compile 与 `git diff --check` 通过。全量真实 Run 验证将在有效 `run.paused` 后加载新 Worker 并继续。

## 2026-09-13 12:27 暂停边界启动恢复补漏

第 9 版 Run 在 sequence 26150 到达真实 `run.paused` 后，平台在原 Run 内追加五角色 `workflow.execution_policy.amended`、针对 `final_report_and_gap_list` 的 `require_rework` 和 `run.restart.requested`。第一次启动新后端时发现：`recover_durable_platform_runs()` 使用 `list_runs_by_status()` 返回的轻量状态行，却直接读取其中不存在的 `events/tasks`，因此服务虽然已启动，仍无法识别重启请求，也不会生成 `run.interrupted` 与 `run.restart.completed`。

修复后，启动恢复会针对每个 paused Run 调用 `get_run(event_limit=200, include_artifact_content=False)`：只加载最近不可变事件、任务状态和 Artifact 元数据，不加载大 Artifact 正文。新增回归测试证明启动器能够读取 sequence 42 的重启请求并写出接管链，同时准确区分 completed 与 pending 节点。

第二次暂停边界重启已在真实 Run 产生 sequence 26153 `run.interrupted` 和 26154 `run.restart.completed`；Run 保持 paused、进度 90%、版本 9。随后 resume 返回 HTTP 200，定向返工 intervention 已 applied，sequence 26252 生成 `workflow.loop.created`，最终报告与 Judge 均回到 pending。新执行回合已按 amendment 启动产品、架构、工程、QA、安全风险五个独立 Claude Code SDK 人物 Session。

五角色首轮均在 sequence 28214～28218 真实命中 1800 秒边界，事件记录 `error_category=timeout`、`next_timeout_seconds=3600` 和 `timeout_extended=true`；3600 秒回合继续产生 Read、Edit、Bash 和测试证据。第二次仍未完成后，sequence 31356 记录 `timeout_seconds=3600`、`next_timeout_seconds=7200`、`timeout_retry_level=1`、`timeout_extended=true`，sequence 31357 随即生成 `task.retrying`。节点整体重试已经继承 7200 秒档位，未回落到 1800 秒。

## 2026-09-13 测试证据完整性补充整改

最终验收不能把 `agent.test.completed` 或零散命令日志等同于测试交付物。对 `run_bda13e93b2ea` 的实际隔离工作区盘点显示，虽然已有测试日志、验证 JSON 和大体积证据包，但工作区内没有 PNG/JPG/HTML/HAR/视频证据，也没有独立的结构化测试用例与逐项结果清单。因而“测试运行过”已有证据，“用户能够复核测了什么、如何操作、页面实际呈现什么、每项是否通过”尚未被证明。

这一缺口被提升为最终发布硬门禁。平台已登记 `intervention_9f1b3ba6c5e8`，sequence 34385，类型 `require_rework`，目标为原 Run 的 `final_report_and_gap_list`；当前成员回合不被强杀，节点结束后在同一第 9 版 Run 内自动返工并重新进入独立 Judge。

返工必须产出并注册：结构化 `test-cases.json`、结构化 `test-results.json`、人类可读测试报告、当前 5173/8003 实例上的 Playwright E2E 报告、关键场景 PNG、失败整改前后截图、`screenshot-index.json`、命令与环境日志。每个文件必须具备 Run/Task/Attempt/Claude SDK Session 血缘、时间戳、SHA-256 和 Artifact Registry 引用，并进入 self-excluding Manifest 与最终证据 ZIP。任何缺失、BLOCKED 或 SKIPPED 都不能被报告为 PASS，最终 Judge 在这些证据没有齐备前不得 ACCEPT。

为保证新证据真正能在产品页面被用户复核，Artifact 文件链路已补齐图片 MIME、原扩展名下载和内联预览。前端新增测试证据门禁汇总，分别显示用例文件、逐项结果、截图及浏览器报告/索引数量；旧 Run 中被错误存为 `application/octet-stream` 的图片也会在下载时按原始文件名重新推断 MIME。截图存储与 HTTP 预览回归 `4 passed`，前端生产构建 1777 modules 通过。sequence 35476 已证明 intervention 被真实执行团队加载，而不是只写入数据库后无人消费。

本次真实浏览器复验还暴露大 Run 介入接口的事件循环阻塞：旧 async handler 在介入写入后同步生成完整公共 Run 投影，当前 Run 已有三万余事件和大量 Artifact，导致 `/api/health`、组织列表和前端初始化一起超过 15 秒，而数据库事件仍持续增长。修复后接口仅返回 `intervention + run_state`，节点名称使用轻量 task summary；前端局部合并响应并继续轮询。新增合同通过 monkeypatch 禁止调用全量 `get_run()`，证明控制面介入不再依赖超大投影。截图与介入链路合计 `5 passed`；旧 Worker 待安全边界重启后生效。

## 2026-09-13 长周期执行策略调整

固定 Run 总执行时长改为显式 opt-in。普通 Workflow 即使仍携带历史 `max_run_minutes` 字段，也不会据此终止；只有同时设置 `enforce_run_time_limit=true` 才启用该上限。平台继续强制单人物/模型回合超时与递增重试上限，保留 Token/成本预算和失败检测，因此“允许执行数天”不等于取消异常保护。

因旧时限终止的 Run 可以在原 Run、原 WorkflowVersion 和原 Artifact Registry 上恢复，`run.recovery_requested` 记录来源失败 sequence、恢复节点和保留节点。历史 epoch 的累计活动时间只用于审计，新恢复 epoch 不会被旧耗时立即耗尽。

长任务页面轮询改用轻量 live snapshot：状态查询直接读取 Run 行、任务摘要、最近 10～300 条事件和 Artifact 元数据计数，不生成全量 node dossier 或加载 Artifact 内容。测试证据摘要在服务端按 Artifact Registry 计算 `test-cases`、`test-results`、图片截图和 Playwright/浏览器报告索引四类数量，运行中即可显示缺口；Run 进入终态后再加载一次完整卷宗供最终复核。

## 2026-09-13 19:40 人物回合取消总时长上限

真实 Version 9 Run 在 `final_report_and_gap_list` 的 epoch29 loop1 中持续产生 Read、Write、Edit、Bash 和测试事件，但成员回合仍在 sequence 49157 命中 1800 秒墙钟边界。平台随后按既有策略创建 `epoch29:loop2:node2`，将下一窗口提升至 3600 秒，并正确写入 `rework_of`、`supersedes` 和 causation；这证明递增重试有效，但也证明“长任务没有总执行时长上限”尚未落实到单人物 Claude SDK 回合。

最终决策是把 `timeout_seconds` 从“回合总墙钟上限”改为“连续无心跳/无输出的停滞窗口”：

- Claude Code SDK Bridge 在执行期间发送内部 heartbeat；该 heartbeat 不进入公开业务事件，不制造测试或进度假象；
- Python Runtime 每收到 heartbeat、模型消息或 Tool 事件都会重置停滞窗口；健康回合可以持续数小时或数天；
- 只有 Bridge 在整个窗口内没有任何输出时，Runtime 才终止进程树并产生 `claude_stalled` timeout；
- 人工取消、进程退出、Provider 错误、Token/成本门禁和 Tool 命令级超时继续生效；
- 现有 `1800 → 3600 → 7200 → 14400` 仅表示异常停滞时的容忍窗口递增，不再限制健康任务累计执行时间。

提交前定向验证：Claude Runtime 合同 `14 passed`，其中新增“总时长超过单个窗口但持续 heartbeat 仍成功”和“无 heartbeat 才终止”两项；Node Bridge `7/7 passed`；Python compile 通过。当前正在运行的 Worker 不热加载该修改，必须等 Run 到达安全终态或明确暂停边界后重启验证。
