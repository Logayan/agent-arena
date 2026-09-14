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
