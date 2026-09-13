# OpenClaw 与 Claude Runtime G5 同题能力对照结果（2026-09-12）

## 目的

在切断产品对 OpenClaw 的依赖前，用同一工程交付合同分别运行 OpenClaw 与 Claude Code Runtime，确认 Claude 替换不造成能力丢失，并为“替换后效果更好”提供可复核的量化基线。本结果只证明 G5 同题工程场景；产品迁移的最终结论仍受真实 UI 端到端 Run、最终 Judge 和 `run.completed` 门禁约束。

## 证据来源

- 机器可读汇总：`experiments/runtime-g5/results/engineering-comparison-final.json`
- OpenClaw Run：`run_9800e0094b6f`
- Claude Code Run：`run_c632a5710385`
- 两组均使用相同必需交付文件合同，并在独立目录执行可移植测试。

## 对照结果

| 指标 | OpenClaw | Claude Code | 结论 |
|---|---:|---:|---|
| Run 状态 | passed | passed | 均完成同题合同 |
| 用时 | 580.616 秒 | 578.682 秒 | Claude 快 1.934 秒，基本持平 |
| Token | 532,961 | 137,515 | Claude 减少 395,446，约 74.2% |
| 可移植测试 | 12 | 15 | Claude 多 3 项，约提升 25% |
| 成功测试证据 | 10 | 13 | Claude 多 3 项，约提升 30% |
| 命令事件 | 38 | 51 | Claude 多 13 项，执行证据更充分 |
| Artifact 校验 | passed | passed | 均满足交付校验 |
| 必需文件 | present | present | 无必需能力丢失 |
| 控制文件泄漏 | none | none | 均通过隔离门禁 |

## 能力等价性结论

两种 Runtime 均完成独立人物提交、公开通信、团队合议、文件创建或修改、命令执行、测试、Artifact 校验和最终 Run 完成。Claude Code Runtime 没有丢失该场景中的 OpenClaw 能力，并以更少 Token 形成更多可移植测试和成功测试证据。

## “效果更好”的限定结论

在本次同题工程合同中，Claude Code Runtime 的用时与 OpenClaw 基本持平，Token 消耗约降低 74.2%，可移植测试数量提升约 25%，成功测试证据提升约 30%。因此可以判定 Claude 在该基线场景中具有更好的资源效率和更充分的测试覆盖。

该结论不得外推为全产品已迁移完成。以下条件仍必须独立通过：

1. 真实前端完成“目标 → 组团队 → 生成流程 → 执行 → 结果”的完整操作链；
2. 真实 Claude Agent SDK Session、工具调用、失败恢复、公开通信、合议、Memory 和 Artifact 均可从平台事件回查；
3. 真实整改后由最终独立 Judge 产生 `gate.passed`；
4. 同一版本 Run 产生 `run.completed`，机器汇总以 `--require-passed` 通过；
5. 产品 Registry、默认配置和生产启动路径不再导入、注册或依赖 OpenClaw。

## 当前判定

- G5 同题工程能力对照：通过。
- Claude 在该场景中的效果改善：通过，有量化证据。
- 全产品迁移：尚未通过，等待第 7 版真实 UI Run 的最终整改、独立裁决和终态门禁。
