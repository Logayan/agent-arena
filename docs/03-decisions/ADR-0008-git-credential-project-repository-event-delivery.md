# ADR-0008：Git 凭据、项目仓库与事件交付分层

- 状态：已实施并通过真实 GitHub 交付验证
- 日期：2026-09-13
- 适用范围：江湖 Online 编码类事件的 Commit、Push 和 Merge Request 交付

## 问题

现实现将 Git Token、仓库 URL、默认分支和交付模式放在同一份 `git_delivery_configs`
中，前端又固定选择 `project_jianghu`。这会让不同事件默认投递到同一仓库，也把
长期凭据与单次交付目标错误绑定。

## 决策

Git 交付拆为三层：

1. **全局 Git 凭据**：保存凭据名称、平台、用户名、API 地址和加密 Token，不保存仓库和分支。
2. **项目仓库**：一个项目可登记零个或多个仓库，保存仓库 URL、默认目标分支、默认交付模式和所用凭据 ID。
3. **事件交付选择**：只有编码或文件修改类事件才选择仓库、目标分支与 `local_commit` / `push_branch` / `create_merge_request`。

Run 创建时冻结仓库 URL、目标分支、交付模式和凭据 ID，不复制 Token。Token 轮换后
仍可由同一凭据 ID 安全接管；历史 Run 的仓库与分支语义不受全局设置改动影响。

## 当前 Claude Code SDK 任务的实施目标

- Run：`run_9226059d74a1`
- 项目：`project_jianghu`
- 仓库：`https://github.com/Logayan/agent-arena.git`
- 目标分支：`master`
- 交付模式：`create_merge_request`
- 凭据来源：Windows Git Credential Manager 中现有 GitHub 凭据
- 安全约束：Token 不出现在对话、命令输出、Run 事件、Artifact 或 MR 描述中

## 验收

1. 凭据可脱离仓库单独保存与测试。
2. 项目可登记多个仓库并分别绑定凭据。
3. 事件可选择其中一个仓库和目标分支；非编码事件可不启用 Git 交付。
4. Run 页面展示冻结的交付目标以及真实 Commit、Push、MR 过程。
5. 应用重启后前后端可用，Git 专项测试和前端构建通过。
