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
  - 5 个真实 E2E 用例，输出 JSON、JUnit、HTML、截图和 SHA-256 Manifest。
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
- 后端定向测试：5 passed，79 deselected。
- 后端完整 API 测试（rebase 前功能提交基线）：84 passed。
- rebase 最新 `origin/master` 后冲突影响集：8 passed，79 deselected。
- `git diff --check`：PASS。

## 部署状态与安全边界

- 正式 5173 前端已通过 Vite 热更新，可刷新页面使用兼容模式。
- 正式 8003 后端仍为旧进程；截至 2026-09-14 11:40（Asia/Shanghai），Run `run_bda13e93b2ea` 仍为 `running / 80% / 迁移验收报告与缺口清单封版`。
- 为避免打断当前 Run，本次没有重启 8003。Run 到达终态后，应受控重启 8003，再执行一次正式全能力 E2E。
- 隔离验证用 5176/5177/8005/8006/8007 均已清理；正式 5173/8003 保持运行。
