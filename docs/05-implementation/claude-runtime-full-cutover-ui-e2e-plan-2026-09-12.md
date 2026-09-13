# Claude Agent SDK 全量切换与 UI E2E 补充计划（2026-09-12）

## 背景

G4/G5 已证明 Claude Adapter、真实文本协作和真实工程协作可以运行，但现有证据主要由后端验收脚本驱动。用户复核后指出：产品启动、Agent 创建、前端状态、事件展示、Docker 依赖和浏览器端完整操作仍存在 OpenClaw 写死项，因此当前不得宣称“完整替换”。

## 本轮目标

只替换 Agent Runtime：把产品实际执行底座、默认 Agent 标记、运行状态、部署依赖和用户可见文案切换到 `claude_code`；组织、团队、Workflow、Run、Judge、返工、Memory、知识、Matrix、API 主体契约和历史数据语义保持不变。

## 已确认缺口

1. 应用启动缺少 Runtime 配置入口，只有测试脚本可临时选择 Claude。
2. Agent API、自动生成人物、Showcase 和数据库默认值仍写死 `openclaw`。
3. Run 启动响应和前端 Runtime 状态仍使用 OpenClaw 名称。
4. 兼容事件类型仍以 `openclaw.*` 命名；为保持历史 API/数据语义，本轮保留读取兼容，但新增事件不得依赖 OpenClaw 实现。
5. Dockerfile/Compose 仍安装和配置 OpenClaw，尚未安装生产 Claude Agent SDK Bridge 依赖。
6. 缺少浏览器实际操作的“目标 → 组团队 → 生成流程 → 创建 Run → 执行 → 查看事件/结果/产物”端到端证据。

## 实施顺序

1. 完成 Runtime 默认选择、Agent 默认值、API/Client 展示和部署依赖切换。
2. 增加迁移兼容：历史 Agent 的 `openclaw` 字段升级为 `claude_code`，历史事件仍可读取。
3. 执行静态残留扫描，将残留分为：历史文档、旧基线测试、兼容别名、待删除生产依赖；生产依赖残留必须为零。
4. 启动 Windows 当前环境的 FastAPI 与 Vue，并确认 Runtime Status 返回 `claude_code`。
5. 使用浏览器操作真实产品，建立新的目标、团队和 Workflow，启动真实 Claude Run，验证实时事件、公开消息、Judge/返工、Artifact、Memory 和结果展示。
6. 执行 pause/resume、cancel/late result、retry、API recovery、Matrix/公开干预边界定向回归。
7. 执行后端全量测试、Node Bridge 测试、前端构建、Python 编译、diff 检查和凭据扫描。

## 通过门禁

- 浏览器 UI 全链路可见通过，且 Run 证据明确记录 `runtime=claude_code`。
- OpenClaw 与 Claude 的同题能力矩阵没有未解释的 `failed` 或缺失项。
- 生产启动与部署不再要求 OpenClaw 包、配置目录或环境变量。
- 兼容保留项必须有明确用途，不能参与新 Run 的实际执行。
- 任何功能丢失、不适配、错误或仅 Fake 覆盖都阻断最终切换结论。

## 当前边界

在上述门禁全部通过前，不删除历史证据，不覆盖用户业务数据，不宣称迁移完成。

## 第 6 版执行进展与剩余门禁

真实浏览器创建并执行的第 6 版 Run 为 `run_d913ce06c52f`。截至 2026-09-12 05:45，已完成 10 个节点中的前 5 个，形成 7 份正式 Artifact；真实工具、文件、命令、测试、公开通信、团队整合、Memory 写回、暂停恢复、后端重启恢复和工程提交均已有平台事件证据。

首轮 Judge 已在平台门禁事件 `gate.rejected`（sequence 4343）中以 42 分、`revise` 正式退回，`workflow.loop.created`（sequence 4344）已将生产流定向返回 `independent_quality_audit`。因此“Judge 退回与平台自动返工”门禁已通过，不允许后续重跑覆盖或替换该证据。

Run 在返工启动时达到原 180 分钟运行上限。已从真实前端选择增加 120 分钟并继续原 Run；`run.time_extended`（4347）、`run.recovered`（4348）和 `agent.runtime.recovered`（4349）证明同一 Run、同一版本、同一产物集合及 `claude_code` Runtime 已恢复。当前正执行独立质量审计的返工回合。

剩余硬门禁只有：

1. 返工后的 `independent_quality_audit` 形成新版本产物，且能回查平台原生 Judge 退回和因果链；
2. `remediation_rerun` 执行真实整改与全链路复验；
3. `final_report_and_gap_list` 形成最终报告与缺口清单；
4. `final_independent_judgement` 由独立 Judge 给出 `gate.passed`；
5. Run 到达 `completed`，所有最终 Artifact 可查询、可下载、哈希可复核；
6. 稳定窗口内无迟到失败事件，并以 `--require-passed` 机器汇总通过。

## 返工阶段新增硬门禁

返工审计已从真实平台事件和文件字节中发现并推动修复三个不能忽略的缺陷：

1. 审计角色必须按节点职责获得 Claude Agent SDK 的 Read/Write/Edit/Bash 工具，不能只给工程人物和 Judge；
2. 审计工作区必须包含经安全过滤的平台公开事件投影和正式 Artifact 原始字节，不能要求审计者复述上游摘要；
3. Artifact 登记 SHA-256 必须与实际落盘原始字节一致，Windows 文本换行转换不能造成哈希断链。

当前实现已增加 `.jianghu-platform-evidence` 证据包、安全事件投影、审计工具授权、UTF-8 Bridge 环境和 Artifact 字节级原子写入。历史 89 份 Artifact 中可证明由平台换行转换产生的存储偏差已通过 `artifact.storage.repaired` 事件修复；当前 Run 7 份 Artifact 的登记哈希和审计副本复算哈希全部一致。

另将 Run 启动/恢复事件中的 Runtime 模式从硬编码改为 Adapter 健康状态。最新第 6 版事件 sequence 4938/4939 已准确记录 `agent-sdk-bridge`。最终 Judge 必须基于修复后的新审计回合和后续新版本 Artifact 裁决，旧审计回合中发现的哈希不一致不得被静默删除或改写。

为防止把隔离 Python Harness 的依赖状态误判为宿主 Runtime，证据包新增 `runtime-attestation.json`。该文件必须显示宿主 `runtime=claude_code`、`mode=agent-sdk-bridge`、真实 SDK/Claude Code 版本，并列出平台事件到 Claude SDK Session 的绑定。当前最新证据为 SDK `0.3.268`、Claude Code `2.1.268`、54 条绑定、7 位实际人物和 54 个不同 SDK Session；最终审计和 Judge 必须引用该宿主 attestation，而不能用 Harness 内 `import claude_agent_sdk` 的结果替代。

公开事件投影现已补齐平台生成的 `event_id`、`run_id` 和 `organization_id`，Session attestation 同步引用来源 event id；Run 元数据已修正 family/version/team 字段。最终门禁新增：事件投影首尾均须属于 `run_d913ce06c52f`，每条 Session 绑定须能回指真实平台 event id，元数据须明确事件家族 `run_0886dd109c15`、第 6 版和真实团队，不接受空值或仅靠目录名推断。

## 第 6 版失败结论与第 7 版恢复计划

第 6 版 `run_d913ce06c52f` 已于独立质量审计阶段真实失败，终态为 `run.failed`，原因 `claude_timeout:1200s`。失败发生在质量工程师第二次人物级尝试完成多轮核验之后；平台事件 sequence 7462–7464 完整保留人物失败、节点失败和 Run 失败。该版本不得再作为“进行中”或“基本通过”描述。

根因分类：

- Claude Agent SDK Bridge、模型请求、Read/Write/Edit/Bash 和测试均在该回合内持续产生真实成功事件；
- 失败不是单项测试断言失败，而是全面审计回合超过当前 20 分钟平台超时；
- 同节点此前已有一次 `claude_timeout:1200s` 并触发节点重试，重复事实证明该上限不适配当前审计规模；
- 审计报告仍给出 `NO-GO` 和未关闭 P0，故即使消除超时，也必须继续后续整改和 Judge 门禁，不能因运行恢复自动改判。

恢复方案已执行：后端在 Windows 当前验证环境中以 `JIANGHU_AGENT_TIMEOUT_SECONDS=3600` 重启，模型、Endpoint、凭据和 Runtime 保持不变；随后通过真实前端从失败节点定向重试，创建第 7 版 `run_7ad4cb297cb5`。该版本保留前 5 个已完成节点，从 `independent_quality_audit` 重新开始，运行快照为 `claude_code / agent-sdk-bridge / gpt-5.6-sol`。

第 7 版新增门禁：

1. 独立审计人物回合必须在 3600 秒上限内自然完成并形成新 Artifact，不接受人工标记完成；
2. 新 Run 必须能回溯第 6 版失败、首轮 Judge 退回及上游 Artifact，且不得复制第 6 版终态事件作为自身通过证据；
3. 审计结论中的未关闭 P0 必须进入 `remediation_rerun`，不能靠延长超时绕过；
4. 最终仍只以本版本链中的真实 `gate.passed`、`run.completed`、Artifact 字节复核和 `--require-passed` 汇总为完成条件。

## 首轮预期退回流程语义修复

第 7 版完成第二轮独立审计后进入 `initial_judge_rejection`。代码复核发现执行器此前把所有 `verdict=revise` 都解释为“回到上游责任节点”，但本 Workflow 明确定义首轮 Judge 必须真实退回，随后由直接下游 `remediation_rerun` 承接整改。旧语义会重复执行 `independent_quality_audit`，无法进入真实整改，最终触发 `revision_exhausted`；这是流程执行缺陷，不是模型裁决问题。

修复决策：

1. 新 Workflow 可使用 `continue_after_rejection=true`，并建议同时声明 `expected_verdict=revise`；
2. 为兼容已经持久化并正在执行的 Workflow，仅当 Judge 的 key、名称或目的明确包含“首轮/首次/initial + 退回/拒绝/不通过”，且存在直接下游 remediation/整改/返工/重跑节点时，启用兼容语义；
3. 预期退回仍必须生成真实 `gate.rejected`，并新增 `gate.expected_rejection.recorded`，payload 标记 `expected_rejection=true`、`continue_downstream=true` 和直接下游节点；
4. 预期退回不创建 `workflow.loop.created`，不把上游审计重新置为 pending，当前 Judge 保持 completed，使下游整改按 DAG 正常就绪；
5. 普通 Judge 的 `revise`、定向责任节点返工、下游重跑、最大返工轮次和最终 `gate.passed` 行为保持不变；没有整改下游时严禁自动继续。

代码与测试已于 09:51 完成。定向辅助测试 6 项通过；新增执行器级闭环测试证明首轮 Judge 只执行一次，同时产生 `gate.rejected` 与 `gate.expected_rejection.recorded`、不产生错误 loop、整改节点真实执行并使测试 Run 完成。另修复轻量测试 Runtime 没有 `health()` 时证据包生成失败的兼容问题，Runtime health 缺失时降级为空 attestation/`unknown` mode，不影响真实 Claude Runtime 的健康信息。

为避免旧执行器在真实 Judge 提交后再次错误回滚，09:51 对后端执行受控中断并保留现场。第 7 版新增 `run.interrupted`（1735）、`run.recovered`（1736）和 `agent.runtime.recovered`（1737），随后从未完成的 `initial_judge_rejection` 边界继续；前端 5173 保持运行。后续硬门禁仍是：预期退回后实际进入 `remediation_rerun`，完成代码、配置、策略和证据整改，再经最终 Judge 产生 `gate.passed` 并由平台产生 `run.completed`。

10:06，真实 Judge 自然完成复审：`agent.turn.completed`（1872）、`artifact.validation.passed`（1876）和 `artifact.created`（1877）形成第 2 版裁决 Artifact。裁决为 `revise`、55 分，列出 24 个未关闭 P0，未把局部 SDK 和工具证据误报为完成。新执行器随后产生 `gate.rejected`（1879），payload 明确 `expected_rejection=true`、`continue_downstream=true`、`impacted_node_keys=[]`；`gate.expected_rejection.recorded`（1880）保存预期退回继续语义。没有新增错误的 `workflow.loop.created`，`remediation_rerun` 在 sequence 1881 真实启动，页面进入 70%。因此“真实退回后进入整改”门禁已通过，后续不得回退到旧循环语义。

10:16，为补齐第 7 版本身的交互恢复门禁，从真实前端点击“暂停并介入”。平台记录 `run.pause_requested`（1986），页面显示正在停手并停止分派下一个受控边界；10:17 从前端点击“恢复行动”，平台记录 `run.resumed`（1987），同一 Run、同一 WorkflowVersion、同一整改节点和已有 Artifact 原样继续。该验证没有修改数据库，且不使用父版本的暂停/恢复事件替代本版本证据。

生产残留扫描进一步收紧 Registry：产品版本不再导入或注册 OpenClaw，不再支持 Legacy 开关；`JIANGHU_AGENT_RUNTIME` 只能为 `claude_code`，误配其他值明确以 `agent_runtime_fixed_to_claude_code` 拒绝启动。OpenClaw Adapter 源码只用于迁移前基线和合同对照，不能成为新 Run 底座。合同测试更新为 50 passed；后端全量测试使用隔离空数据库完成 105 passed；Bridge 6/6、前端 1777 模块生产构建通过。凭据扫描唯一命中是 NIST URL 中 `risk-management` 的 `sk-` 子串假阳性，没有发现已知格式的真实密钥落盘。
