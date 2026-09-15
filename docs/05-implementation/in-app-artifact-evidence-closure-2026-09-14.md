# 应用内 Artifact 证据闭环与历史字节血缘修复

日期：2026-09-14
目标 Run：`run_bda13e93b2ea`（Version 9）

## 问题结论

页面出现 `Not Found` 和“只能看到文件元数据”由三类问题叠加导致：

1. 5173 前端已加载新证据中心，但正式 8003 后端仍是旧进程，没有 Artifact 详情、缩略图和内容来源接口；直接请求新路由会返回 404。
2. 正式交付区一次渲染 2,935 份 Artifact，页面长时间停在“正在读取江湖状态”，且旧交付卡片展开后只展示变更回执。
3. 历史定向重试用 `create_artifact(content)` 继承 `runtime_file`，把真实源文件降级成 `{source_relative_path, sha256}` 文本回执。父 Run 的真实字节仍然存在，但当前 Run 的旧 Artifact 只保存了回执字节。

## 实现决策

- Artifact Registry 的登记记录保持不可变，不覆盖旧 Artifact 的 SHA 或文件。
- 新增“实际内容来源”解析：当历史 `runtime_file` 的登记 SHA 与回执中的源 SHA 不同，先按源 SHA 查找精确 Artifact，再回退到 `artifact.inherited` 血缘；应用内预览读取来源 Artifact 的真实字节。
- 新的重试继承不再复制 `content` 元数据，而是逐字节复制源 Artifact，保持 SHA-256、媒体类型和大小。
- 旧正式后端运行期间使用能力探测兼容模式：不调用不存在的新接口，图片和文本走旧 `/download?inline=true`，页面不展示裸 404。
- HTML/PDF 先 fetch 校验并生成 Blob URL，再放入沙箱 iframe；失败时展示中文原因，不把后端 `Not Found` 页面嵌入应用。
- 大文本使用 HTTP Range 真实读取前 512KB，并明确标注截断范围；不再因超过 1.5MB 而只显示元数据。
- 正式交付区按生成时间倒序，每类首次只渲染 24 份并按需加载，避免 2,935 张卡片一次性挂载。

## 代码范围

- `client/src/App.vue`
  - 测试与证据中心、来源详情、应用内正文/图片/HTML/PDF 预览。
  - 正式交付卡片新增“应用内查看文件”。
  - Artifact 分组倒序和 24 份分页加载。
  - 旧后端 capability fallback 与友好错误。
- `client/src/api.ts`
  - Artifact detail、thumbnail、content、Range 文本和 Blob 预览。
- `client/src/evidence-center.css`
  - 证据中心、灯箱、正文、回执和分页样式。
- `client/e2e/evidence-center.mjs`
  - 7 个真实 E2E 用例，输出 JSON、JUnit、HTML、截图和 SHA-256 Manifest。
- `server/app/platform_store.py`
  - Artifact 内容来源血缘解析。
  - `runtime_file` 重试继承真实字节。
  - Artifact 事件查询时间窗索引。
- `server/app/main.py`
  - Artifact 详情、实际内容和 WebP 缩略图接口。
- `server/tests/test_api.py`
  - 详情/回执、旧血缘回溯、缩略图缓存、重试字节继承测试。

## 验证结果

### 正式服务兼容模式

环境：5173 前端 + 8003 旧正式后端 + 当前真实 Run。

- 5/5 PASS。
- console errors：0。
- failed requests：0。
- HTTP 4xx/5xx：0。
- 结果：`deliverables/run_bda13e93b2ea/evidence-center-e2e/compat-live-20260914-final/`

覆盖：

1. 打开真实 Run 的证据中心。
2. 查看并切换真实截图。
3. 旧后端下友好回退来源回执。
4. 在应用内查看 JUnit/XML 正文。
5. 从正式交付卡片直接打开真实源文件正文。

### 全能力隔离模式

环境：5177 前端 + 8007 禁止恢复任务的快照后端 + 生产 Artifact 字节只读映射。

- 5/5 PASS。
- console errors：0。
- failed requests：0。
- HTTP 4xx/5xx：0。
- 结果：`deliverables/run_bda13e93b2ea/evidence-center-e2e/full-lineage-20260914-final-r2/`

历史 Artifact `artifact_953213e57d6e` 验证：

- 当前记录：138 字节元数据回执。
- 解析来源：`artifact_917a5d39cc7c`。
- 应用内实际内容：11,173 字节 Python 文件。
- 内容 SHA-256：`0d141e028b738b8cc8c951800dc61eda613779b782629982ca5bbed7b3b87330`，与源登记 SHA 完全一致。
- 详情解析耗时：约 2.7 秒。

### 自动化测试

- 前端生产构建：1778 modules，PASS。
- 后端定向测试：4 passed，84 deselected（本轮真实内容解析影响集）。
- 后端完整 API/Runtime 回归：188 passed（包含删除前字节回溯、增量工作区复制和证据缓存排除的新回归用例）。
- Claude Agent SDK Bridge：8 passed。
- rebase 最新 `origin/master` 后冲突影响集：8 passed，79 deselected。
- `git diff --check`：PASS。
- Secret Scan：PASS。
- OpenClaw 生产残留分类扫描：PASS。正式 Runtime 为 `claude_code / agent-sdk-bridge`；生产 Registry 只构造 Claude 默认底座并拒绝非 Claude 配置；生产 Adapter 文件、Import、部署依赖和环境开关均不存在，blocking findings 为 0。历史基线仅保留在 `experiments/openclaw_baseline` 和 Runtime 合同测试中。

## 部署状态与安全边界

- 正式 5173 前端已热更新；正式 8003 已在 Run 安全失败终态后受控重启并加载全能力代码。
- 正式 5173 + 8003 全能力 E2E 已在最终代码上再次执行：5/5 PASS，console errors、failed requests、HTTP 4xx/5xx 均为 0；结果位于 `deliverables/run_bda13e93b2ea/evidence-center-e2e/formal-full-20260914-r3/`。
- 正式应用人工复核：从交付卡片打开 `independent-judge-final-e33/verify_current_snapshot.py`，应用内返回 51,271 字符 Python 正文，首行是 `#!/usr/bin/env python3`，不是元数据回执且未出现 `Not Found`。
- 页面下载与原图入口统一读取 `/content` 解析后的实际内容，不再下载旧回执本身；`download=true` 提供正确文件名和附件响应头。
- 删除 Artifact 也按 `previous_sha256` 尝试回溯删除前字节，并限定在同一组织内查找，避免跨组织内容串读。正式 Run 的 339 份删除记录中，315 份可恢复删除前原文件，24 份只能诚实展示删除凭据。
- `artifact_809cec5f22d8` 已从 299 字节删除元数据回执解析为 1,153 字节 Markdown 原文；`artifact_953213e57d6e` 下载为 11,173 字节 Python 原文，文件名为 `test_runtime_acceptance-v1.py`。
- 原 Run `run_bda13e93b2ea` 已从 `task_764f124e78e1` 原地恢复，历史失败事件和 2,935 份既有 Artifact 均保留。
- 恢复性能修复：相同 size 与 mtime 的工作区种子文件跳过重复复制；`.jianghu-platform-evidence` 不再参与每个 Agent 的交付变更快照；取消接口不再加载 2,935 份 Artifact 正文。候选工作区约 9.26GB 时，避免五角色重复复制约 46GB 的无效 I/O。

## 14:00 后再次复核与兼容入口补齐

用户再次报告“点开是 Not Found、只看到元数据”后，直接对正式 `5173 + 8003` 和 Run Version 9 复验：

- 从当前 2,935 份 Artifact 中抽取 16 份 runtime file / workflow output，逐份请求 `/content`，全部 HTTP 200；最大样本 `证据索引.json` 返回 2,901,614 字节真实 JSON。
- 正式浏览器 E2E 在 `deliverables/run_bda13e93b2ea/evidence-center-e2e/user-not-found-recheck-20260914/` 再次达到 5/5 PASS，console errors、failed requests、HTTP errors 均为 0。
- 发现仍有一个向后兼容遗漏：浏览器缓存中的旧页面或历史外链会继续请求 `/download`。该入口此前只读取当前 Artifact 物化文件，遇到继承回执或删除回执仍可能 404。现已把 `/download` 统一接入 `artifact_content_file_path()`，与 `/content` 使用同一实际内容血缘；旧页面、旧链接和新版证据中心得到一致字节。
- 继承回执、删除前文件和图片旧下载入口影响集 3/3 PASS；后端全量回归更新为 191 passed；Claude SDK Bridge 更新为 10/10；前端生产构建仍为 1778 modules。

同一轮还补齐了独立验收所需的底层证据关联：

- 每个 Claude SDK Tool Call/Result 持有 SDK invocation、SDK Session、Tool Use ID、request/result digest。
- Tool Schema 增加稳定 `schema_version=1.0.0` 与输入 Schema 原文。
- Write/Edit MCP 结果增加对象 ID、before/after/read-back SHA、write count 与 duplicate count。
- 人物完成、提交和团队成员完成事件增加当前 `platform_attempt_id`、角色实例、审批凭据、平台 Session、SDK Session 与 SDK invocation，避免真实完成回合被审计误判为 0。
- 新增角色×Tool 最小权限正负矩阵、十入口 Registry 观察窗，以及公开投影 omission 的逐 sequence 原因码与策略版本。
- Claude SDK Bridge 心跳将进入公开事件，长回合在页面显示“仍在执行”，不再只能依赖进度百分比判断是否卡住。

上述后端 Runtime 证据合同变更必须等待当前 epoch36 已放行回合自然完成后再受控重启加载；当前 Run 仍保持原 ID、原 Version、原历史事件和 Artifact，不在运行中强制中断。

## 14:48 正式服务加载修复与应用内闭环复验

再次核对发现，工作区代码虽然已经修复 Artifact 内容解析，但正式 8003 仍是 12:35 启动的旧进程，因此用户当前浏览器仍可能命中旧 `/download` 行为。数据库证据显示 epoch36 最后一个人物回合已在 14:25 完成，14:44 已生成暂停 Checkpoint，之后没有新的业务事件；残留 Bridge/Claude 进程属于旧后端未收尾，不是仍在正常审计。

平台先在同一 Run 写入 `run.restart.requested`，再停止已核验的旧后端进程树并启动新版 8003。启动恢复把 `pause_requested` 固化为 `paused`；第二次在真实 paused 边界重启后，sequence `104434/104435` 形成 `run.interrupted` 与 `run.restart.completed`，证明服务进程切换没有覆盖历史现场。

正式接口抽查结果：

- `artifact_507d541634bf`：`/content` 与旧 `/download` 都返回 HTTP 200、2,901,614 字节真实 JSON，SHA-256 为 `b02a2e76355c847abb8c58a798949a76b9b6c667355c9ffd5c83ca95c851ae21`；
- `artifact_24f247f8e663`：两个入口都返回 14,776 字节 Markdown 正文，首行是 `# Claude Agent SDK 全链路迁移｜最终独立验收裁决`；
- `artifact_9631a2287609`：两个入口都返回 1,513 字节验证日志；
- 三组返回字节的 SHA-256 均与 Artifact Registry 完全一致。

正式 `5173 + 8003` 浏览器套件 `not-found-final-20260914` 再次达到 5/5 PASS，`console_errors=0`、`failed_requests=0`、`http_errors=0`。用例覆盖从真实 Run 打开证据中心、截图灯箱、来源与校验回执、测试材料正文，以及从正式交付卡片进入应用内真实文件预览。结果目录为：

```text
deliverables/run_bda13e93b2ea/evidence-center-e2e/not-found-final-20260914/
```

为满足应用内闭环，本套件的 `test-cases.json`、`test-results.json`、JUnit、HTML 报告、SHA Manifest 和 5 张截图共 11 份文件已登记回原 Run；每份均生成 `artifact.created`、`artifact.collected`、`artifact.download.verified`，sequence `104469` 记录 `evidence.center.e2e.completed`。其中交付卡片正文截图 Artifact 为 `artifact_c93dd59f473a`，`/content` 返回 HTTP 200、207,280 字节 PNG。

同一 Run 随后从 Version 9 恢复到 execution epoch 37。sequence `104511` 证明 13/13 份生产 Runtime、SDK Bridge、前端与部署源码已作为真实可下载字节进入 Registry；`final_report_and_gap_list` 已重新开始，最终独立 Judge 仍保持 pending。此时只能确认 Not Found/元数据问题闭环通过，不能提前宣布整项 Claude SDK 迁移验收完成。

## 16:30 无扩展名正文、缺字节凭据与大 Run 按需读取补齐

用户继续复核时发现两类仍会被误解为“只有元数据”的实际遗漏：`Dockerfile`、`.env.docker.example` 等无标准扩展名文本在 Registry 中历史登记为 `application/octet-stream`；另有少量删除凭据的删除前原字节从未进入 Registry。与此同时，完整 Run 接口仍会一次读取全部 Artifact 的 `content`，在 1.1GB SQLite、2,960 份 Artifact 和持续写入的现场上放大首屏等待时间。

本轮对正式 Run 的 2,960 份 Artifact 做了完整分类：2,617 份直接持有真实字节，319 份可以按来源 SHA-256 回溯真实原文件，24 份属于删除前字节从未归档的历史删除凭据。后 24 份无法凭空恢复，因此页面必须诚实显示“删除证据元数据”，不能把回执冒充为原文件正文。

实现补齐：

- 后端按文件名重新识别 Dockerfile、`.env*`、Makefile、配置、代码、CSV 等文本；历史 `application/octet-stream` 登记不被篡改，但 `/content` 使用可预览的实际媒体类型响应。
- Artifact 详情增加 `content_resolution`，明确区分 `direct`、`resolved`、`receipt_only`、`missing`，并返回原字节可用性、请求/解析 SHA 与错误原因。
- 完整 Run 接口只返回 Artifact 元数据；正文继续通过 Artifact `/content` 按需获取，避免首屏搬运全部历史正文。
- 前端根据来源路径、文件类别和文件名识别无扩展名文本；下载前先核验详情，失败时留在应用内说明原因，不再把整个页面导航到 `Not Found`。
- 删除前原字节缺失时显示明确警告：“下方展示的是删除证据元数据，不会把它冒充为文件正文”；此时下载按钮下载的是删除凭据，而不是伪造原文件。
- E2E 新增 Dockerfile/.env 正文和 receipt-only 友好闭环两项，并修复图片导航后错误检查相邻 Artifact 的测试状态问题。

最终验证：

- 正式 `5173 + 8003`、当前真实 Run、2,960 份 Artifact：7/7 PASS；console errors、failed requests、HTTP 4xx/5xx 均为 0。结果在 `deliverables/run_bda13e93b2ea/evidence-center-e2e/not-found-content-fix-formal-r2-20260914/`。
- 隔离 `5175 + 8005`、禁恢复的真实快照后端：7/7 PASS；三类错误均为 0。结果在 `deliverables/run_bda13e93b2ea/evidence-center-e2e/not-found-content-fix-isolated-r2-20260914/`。
- 人工检查正式截图确认：Python 正文、Dockerfile 正文和 receipt-only 中文警告都实际可见，不是只验证 DOM 元数据。
- 后端 API/Runtime 完整回归：182 passed。
- Artifact 影响集：6 passed；Claude Agent SDK Bridge：10 passed；前端生产构建：1778 modules；`git diff --check` 与差异 Secret Scan 通过。

正式 Run 在验证期间仍持续产生 Claude Code SDK 工具事件，因此没有为加载本轮 Python 后端优化而强制重启 8003。当前正式页面已经通过前端兼容路径实现 7/7 闭环；轻量 Run 投影和显式 `content_resolution` 将随下一次安全边界重启加载，不以中断正在执行的 Agent 为代价。

## 18:10 冷缓存大截图、轻量 Registry 清单与真实正文复验

针对用户看到的 `Not Found` 和“只有文件元数据”，再次沿正式页面、API 与物化文件三层核验。正式 `/content` 对 `client/src/api.ts` 返回 HTTP 206 和真实 TypeScript 字节；`test-cases.json` 在应用内展示 EVC-001 至 EVC-005 的实际 JSON 正文；截图缩略图返回有效像素，不是元数据占位。根因仍是旧交互曾把 `runtime_file` 登记回执当正文，并让浏览器直接跳转下载；当前实现已经统一先解析实际内容 Artifact。

本轮又发现两个与大 Run 有关的体验问题：完整 Run 投影在 112,000+ 事件和 2,961 份 Artifact 下可能超过五分钟；证据中心冷缓存时并发生成多张超长截图缩略图，会让选中图片请求排在浏览器连接队列之后。处理如下：

- 新增 `/api/platform/runs/{run_id}/artifacts` 轻量清单，只读取 Artifact Registry 元数据，不构建完整 Run dossier，也不搬运正文；
- 现场轮询检测到 `artifact_count` 变化时，通过轻量清单刷新真实文件列表；旧后端尚未加载该能力时保持兼容，不中断状态轮询；
- 截图筛选首批由 24 份收敛为 8 份，列表缩略图使用低优先级，选中图使用高优先级；灯箱复用缩略图响应，原始字节仍由“原图”下载入口提供；
- E2E 不再依赖完整 Run 投影，改为并行读取轻量状态、Artifact 清单和 Run 摘要；图片用例先按 Artifact ID 收敛列表，再验证真实图片解码和可见尺寸；
- Windows 取消合同测试不再固定等待 0.2 秒，而是等待 Bridge 写入启动 marker 后取消，消除高负载竞态。

隔离快照 `5175 + 8005` 的最终真实 E2E 为 7/7 PASS，`console_errors=0`、`failed_requests=0`、`http_errors=0`，结果目录为 `deliverables/run_bda13e93b2ea/evidence-center-e2e/isolated-current/`。后端 API/Runtime 完整回归更新为 184 passed，Runtime 合同 91 passed，前端生产构建 1778 modules。正式 5173 页面已人工复验真实 JSON 正文与真实截图；正式 8003 因 Run 仍有 Claude Bridge 心跳，继续等待真实 paused 安全边界后再加载本轮 Python 接口变更。

## 19:25 正式后端版本错配复核与最终现场验证

用户再次看到 `Not Found` 和“只有元数据”后，对正式端口进行源码、进程能力与浏览器三方比对，确认当时存在明确的前后端版本错配：

- 5173 已通过 Vite 热更新加载 Artifact 轻量清单和应用内正文代码；
- 工作区当前提交已声明 `artifact_listing=true`，并实现 `/api/platform/runs/{run_id}/artifacts`；
- 但 8003 仍是提交前启动的旧 Python 进程，健康响应没有 `artifact_listing`，请求轻量清单直接返回 `404 {"detail":"Not Found"}`。

Run 已处于 `failed` 安全终态，因此受控重启正式 8003 加载当前代码，不创建新 Run、不改变 Version 9，也不覆盖任何历史事件或 Artifact。重启后：

- `/api/health.capabilities.artifact_listing=true`；
- `/api/platform/runs/run_bda13e93b2ea/artifacts` 返回 4,170 份 Artifact；
- 物化文件完整性扫描为 4,170/4,170 存在、0 缺失、0 大小不一致；
- 其中 4,134 条数据库 `content` 是不可变的文件变更审计回执，页面正文必须通过 `/content` 解析真实物化字节，不能直接把该字段当正文；
- Markdown、JSON、PNG、HTML、TypeScript 五类正式样本均通过 HTTP Range 返回 `206` 和真实字节，没有 404。

同时修复 E2E 导航：轻量 `/state` 投影不包含 `run_family_id`，而历史事件列表展示的是 Run Family，不是 Version 9 的物理 Run ID。测试现在并行读取 Run Detail，取得 `run_0886dd109c15` 后再选择 Version 9，避免在进入测试步骤前误超时。

正式 `5173 + 8003` 最终结果：

- Evidence Center E2E：7/7 PASS；
- console errors：0；
- failed requests：0；
- HTTP errors：0；
- 输出目录：`.codex-build/evidence-center-e2e/formal-final/`；
- API/业务完整回归：108 passed；Runtime 合同：91 passed；前端生产构建：1778 modules；
- 批量 Artifact 归档增加启动对账：若进程在 Registry 已提交、Manifest 批次未刷新时中断，重启会只补齐缺失 ID；恢复操作幂等；
- 正式应用已停留在 Run `run_bda13e93b2ea` Version 9 的证据中心，并打开 `x/r/test-cases.json` 的真实 JSON 正文供现场复核。

## 20:27 登记回执与实际文件信息拆分

用户现场反馈“点开是 Not Found，且看到的都是文件元数据”。复核确认当前 `/content` 已能按 SHA-256 和 `artifact.inherited` 血缘返回真实字节，但历史继承 Artifact 的详情面板仍把“登记回执”的大小、类型和 SHA 当成主文件信息。例如 `artifact_a16cef0665d1` 的回执仅 136B / `text/markdown`，真实内容来源 `artifact_336f6a0da12b` 为 27,494B / `application/json`。这个展示错位会让用户误判为页面仍只有元数据。

前端现已将两者拆分：

- 主信息显示“实际文件 SHA-256”和“实际文件大小 / 类型”；
- 只在发生血缘解析时单独显示“登记回执 SHA-256”、“登记回执大小 / 类型”和实际内容来源 Artifact；
- 增加明确提示：下方预览和下载使用真实文件字节，回执仅用于审计。

真实正式服务 `5173 + 8003` 新增 EVC-008 后为 `8/8 PASS`，`console_errors=[]`、`failed_requests=[]`、`http_errors=[]`。EVC-008 实际打开 `artifact_a16cef0665d1`，读取 27,452 个预览字符，`receipt_only=false`，并保存 `08-inherited-receipt-real-content.png`。前端生产构建通过（1778 modules），Artifact 内容解析影响集 4/4 通过，新增启动快照缓存测试 2/2 通过。

20:38 至 20:39 又在正式 `5173 + 8003`、同一 Run Version 9 上按最终工作区代码完整重跑 8 项 Evidence Center E2E，结果仍为 `8/8 PASS`，浏览器 console、failed request、HTTP 4xx/5xx 均为 0；证据目录为 `deliverables/run_bda13e93b2ea/evidence-center-e2e/final-recheck-20260914/`。随后完整 `server/tests` 回归为 201 passed，Runtime 合同为 91 passed，Claude Agent SDK Bridge 为 10/10 passed，差异 Secret Scan 为 0 命中，OpenClaw 生产路径阻断项为 0。最终 Judge 仍以其冻结快照和正式机器 verdict 为准，不能用本地回归提前替代 `gate.accepted`、`run.converged` 或 `run.completed`。

## 21:15 用户现场再次点击复核

再次从正式 `5173 + 8003` 页面检查同一 Run Version 9。历史错误由两个层面组成：旧页面/旧服务曾请求未注册的 Artifact 路由而返回 FastAPI `404 {"detail":"Not Found"}`；历史继承 Artifact 本身又只物化了 `{source_relative_path, sha256}` 登记回执，导致即使请求成功也像“只有元数据”。

当前正式接口与页面验证：

- `GET /api/platform/artifacts/artifact_a16cef0665d1` 返回 `content_resolution.state=resolved`，实际内容来源为 `artifact_336f6a0da12b`；
- `GET /api/platform/artifacts/artifact_a16cef0665d1/content` 返回 HTTP 200、27,494 字节 `application/json`；
- 页面主信息显示真实文件 27 KB，登记回执 136 B 单独显示，正文区域实际渲染 27,452 字符 JSON；
- 正式 E2E 再次为 8/8 PASS，`console_errors=[]`、`failed_requests=[]`、`http_errors=[]`；
- 本次证据目录为 `deliverables/run_bda13e93b2ea/evidence-center-e2e/user-not-found-recheck-20260914/`，关键截图为 `screenshots/08-inherited-receipt-real-content.png`。

因此当前页面已不再把 Artifact 的数据库 `content`/登记回执当作文件正文，也不再通过文件系统相对路径打开文件；预览和下载统一经 Artifact 内容 API 与 SHA-256 血缘解析读取真实字节。若浏览器仍停留在旧的 `Not Found` 页面，需要返回原事件现场或刷新正式前端页面，旧 404 页面本身不会自动切换成证据中心。

## 22:10 大 Run 下 Artifact 详情查询退化修复

用户再次现场点击时，5173 前端与 `/api/health` 可以立即响应，但 8003 的 Artifact 详情和 `/content` 请求在 12 至 30 秒观察窗内无返回。数据库与页面双向核验确认真实文件没有丢失：`artifact_a16cef0665d1` 仍能解析到 `artifact_336f6a0da12b`，正式页面已展示 27 KB `application/json` 和 27,452 字符真实正文。问题是大 Run 下的来源回执查询退化，而不是文件不存在。

对 1.2GB 正式 SQLite、121,000+ Run 事件进行查询计划和实测：Artifact ID 主键查询为 0.0003 秒，来源 SHA 查询为 0.0218 秒；回执事件查询虽然已有 `idx_events_artifact_lookup(run_id,type,created_at)`，SQLite 为满足 `ORDER BY sequence` 仍错误选择 `UNIQUE(run_id,sequence)`，导致扫描整个 Run，单次耗时 10.4441 秒。显式使用目标索引后同一查询为 0.0066 秒，约快 1,580 倍。

存储层现对 SQLite 的 Artifact 回执查询显式使用 `idx_events_artifact_lookup`，PostgreSQL 保持原生 Planner 语法；同时新增 `idx_artifacts_content_source(organization_id,sha256,created_at DESC)`，避免来源血缘增长后退化。索引创建放在历史库补齐 `sha256` 字段之后，兼容新库和旧库迁移。Artifact 详情、继承正文、删除前原文和 receipt-only 状态影响集 5/5 通过；编译与 `git diff --check` 通过。

当前正式 Run 仍在 Claude Code SDK 人物回合中，因此没有为加载 Python 查询修复而重启 8003。正式页面已经证明真实正文存在；查询计划修复将在本 Run 到达安全终态后随受控重启加载，并再次执行正式 8 项 Evidence Center E2E。

## 22:35 当前 Attempt 证据镜像路径与流式快照修复

实时事件显示本轮质量角色把 required snapshot `attempt-1ca0ec288c311cb8` 判为 `P0_OPEN_FAIL_CLOSED`。宿主 `code/.jianghu-platform-evidence/snapshots/attempt-1ca0ec288c311cb8` 的 9 个文件全部存在，但人物隔离区的 `delivery/.jianghu-platform-evidence/snapshots/` 只到旧的 `attempt-4a033a0d311ace74`。根因是 Executor Prompt 给出相对 delivery 的 `.jianghu-platform-evidence/...`，Runtime 却把新快照镜像到 delivery 的父级 workspace；人物以 delivery 为 cwd，按合同路径无法读取本次快照。

Runtime 现将当前 Attempt 快照及其内容寻址 Artifact 直接镜像到 `delivery/.jianghu-platform-evidence`。该目录已被文件变更快照明确排除，因此只读证据不会被采集或晋升为人物交付。对应 Claude Bridge 合同 2/2 通过。

同时将证据包构建从“全量事件反序列化 + 279MB NDJSON 字符串 + 200MB critical 列表同时驻留内存”改为每批 1,000 条事件流式投影：三个输出先写 `.tmp`，完成后原子替换；只在内存保留 `agent.turn.completed` 的 Runtime Session 绑定小集合。Artifact 血缘只加载 `artifact.created`、`artifact.inherited` 与 `run.retry_created`，Run 元数据使用独立事件计数。流式快照影响集 6/6、完整 Runtime 合同 94/94 通过。

为确保路径修复在下一轮 Judge 前加载，sequence `122868` 已请求安全暂停。当前人物回合继续自然完成，平台只会在节点边界生成 Checkpoint 并暂停，不杀进程、不覆盖本轮 P0 证据。
