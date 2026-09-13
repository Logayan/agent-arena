# Git 凭据、项目仓库与事件交付实施结果

日期：2026-09-13

## 实施结果

Git 交付已从“每个项目一份混合配置”拆分为：

1. 全局 Git 凭据库：只保存平台、用户名、API 地址和加密 Token。
2. 项目代码仓库：同一项目可登记多个仓库，每个仓库可分别绑定凭据、默认分支和交付方式。
3. 事件交付选择：只有编码或文件修改事件才启用，并为该事件选择仓库、目标分支和 Commit / Push / MR 模式。
4. Run 冻结交付目标：仓库、分支、凭据 ID 和交付方式进入 Run 记录，Token 不进入 Run、事件或 Artifact。

## 当前 Claude Code SDK Run 配置

- Run：`run_9226059d74a1`
- 项目：`project_jianghu`
- 凭据：从 Windows Git Credential Manager 安全导入的 GitHub 凭据
- 仓库：`https://github.com/Logayan/agent-arena.git`
- 目标分支：`master`
- 交付方式：`create_merge_request`
- 远端隔离分支：`jianghu/run_9226059d74a1/run_delivery_backfill`

## 真实远端结果

- Run 隔离源 Commit：`303f351a82a8b22a94f15bb8f31ac5139ceb4479`
- 核心实现文件历史锚定后的远端 Commit：`f3f823a51cbeb5f57848501334897a8a7bba9f5c`
- Merge Request：[GitHub PR #4](https://github.com/Logayan/agent-arena/pull/4)
- MR 状态：`open`
- MR 已复用同一事件的远端分支，后续实现和文档通过 fast-forward 持续更新。
- 核心实现推送后的验证快照：95 files changed，21967 additions，407 deletions；最终差异以 GitHub MR 页面为准。

## 历史锚定修复

Run 隔离仓库与目标仓库没有共同祖先时，不再直接使用 Run 完整 Tree 覆盖目标仓库。
交付器现在以目标分支 Tree 为基础，覆盖 Run 中真实交付的文件，保留目标仓库中与本次事件无关的文件。
已验证同一隔离分支后续更新为 fast-forward，不需要 Force Push。

## 验证

- Git Runtime Contract：`6 passed`
- Git 凭据 / 项目仓库 / Run 绑定存储测试：`1 passed`
- 前端 TypeScript 与 Vite 生产构建：通过，1777 modules transformed
- Python compileall：通过
- 前后端端口：`127.0.0.1:5173` 和 `127.0.0.1:8003` 均正常监听
- Runtime 健康：`claude_code / available=true`
- 远端仓库连接：成功读取 3 个分支
- MR 最终选定的 10 个核心修改文件与当前工作区 Blob 完全一致
- MR 差异敏感信息扫描：0 个 GitHub Token、0 个 API Key、0 个私钥命中
- 浏览器验证：“Git 凭据库”与“项目代码仓库”分类展示，事件入口提供可选 Git 交付区域。
