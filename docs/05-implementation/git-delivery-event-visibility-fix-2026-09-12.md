# Git 交付事件可见性修复记录

日期：2026-09-12

## 问题

Claude Code SDK 迁移 Run 的页面只出现 `git.workspace.ready`，没有显示 Commit 创建过程、Commit Artifact 或可下载 Patch。

## 根因

- `run_9226059d74a1` 的前五个节点在 Git 提交能力加入前已经完成。
- 后端恢复时不会重新执行已完成节点，因此只初始化了 Run 隔离 Git 仓库，没有补录历史文件提交。
- `commit_run_changes()` 在工作区干净时返回 `None`，旧逻辑没有生成明确的跳过事件。
- `git.workspace.ready` 是 Run 全局事件，不含 `task_id`，旧页面仅在节点行动与证据面板筛选 Git 事件，因此全局 Git 阶段不够明显。

## 修复

### 执行事件

新增并展示完整生命周期：

1. `git.workspace.ready` / `git.workspace.unavailable`
2. `git.delivery.planned`
3. `git.commit.started`
4. `git.commit.skipped` / `git.commit.failed` / `git.commit.created`
5. `git.commit.verified`
6. `git.remote.started`
7. `git.remote.pushed` / `git.remote.failed`
8. `git.merge_request.created`

工作区没有变化时必须写入 `git.commit.skipped` 和 `working_tree_clean` 原因，不再静默结束。

### 页面展示

- 在正式交付区域顶部增加独立的“Git 交付执行过程”时间线。
- 全局 Git 事件不依赖节点 `task_id`，可直接查看仓库初始化、计划、Commit、Push 和 MR 状态。
- “Git 工作区就绪”不再造成已经提交的误解：没有 Commit 时明确显示“尚未产生 Commit”，说明仍在等待工程节点通过文件与测试校验，并提供“查看待提交节点”。
- Commit 事件提供“查看提交内容”“复制 SHA”“下载 Patch”三个操作。
- “查看提交内容”会滚动并展开对应的 Commit Artifact 卡片，显示完整 SHA、作者、分支、提交时间、变更统计和文件清单。
- Git Commit Artifact 继续单独展示 Commit SHA、作者、分支、文件清单和 Patch 下载入口。
- 浏览器 Run 详情固定读取最近 300 条事件；完整事件继续保存在 SQLite。

## 当前 Claude Code SDK Run 的真实补录

- Run：`run_9226059d74a1`
- 隔离仓库 Commit：`52c24a6298ef1a9957d945445745b0c888ee653a`
- Commit Artifact：`artifact_deff6106a747`
- 变更：85 files changed，17036 insertions
- Patch SHA-256：`62db913f3c5a0968f31188d8c9b35844d4ce134c70e2f72d4fe837ed87e95455`
- Artifact 字节复核：通过
- Patch 下载接口：返回 `200`，937251 bytes
- 已写入事件：`git.commit.started`、`git.commit.created`、`git.commit.verified`

这是 Run 隔离代码仓库中的真实 Commit，不是宿主源码仓库的 Commit，也没有伪造远端 Push 或 Merge Request。当前项目未配置远端 Git 交付，因此本次只形成 `local_commit`。

## 验证

- Git 专项测试：5 passed。
- 前端 TypeScript 检查和 Vite 构建通过。
- Python 编译通过。
- `git diff --check` 通过。
- 页面 API 返回 Git 生命周期事件和一个 `git_commit` Artifact。
- 300 条事件窗口请求返回 `200`，现场约 2.70 秒。
- 活动 Run `run_bda13e93b2ea` 已在恢复后写入 `git.delivery.planned`。
- 浏览器端到端验证：
  - 未产生 Commit 的运行版本显示等待状态和“查看待提交节点”；
  - `run_9226059d74a1` 显示真实 Commit SHA 和三个操作入口；
  - 点击“查看提交内容”后成功定位并展开 `artifact_deff6106a747`，页面展示 85 个变更文件及 Patch 下载入口。
