# Claude SDK Run 恢复 Attempt 血缘修复

日期：2026-09-13  
验收 Run：`run_bda13e93b2ea`  
Run Version：`9`

## 问题证据

execution epoch 31 的 `attempt.created`（sequence `62763`）包含以下相互矛盾的字段：

```json
{
  "platform_attempt_id": "attempt:run_bda13e93b2ea:final_report_and_gap_list:epoch31:loop1:node1",
  "rework_of": null,
  "rework_of_run_id": "run_9226059d74a1"
}
```

该 Attempt 是 `run_bda13e93b2ea` 在同一 Run、同一 Version 内恢复后创建的新 execution epoch，并不是父 Run `run_9226059d74a1` 的首次跨 Run 重试。根因是新 epoch 会把 `loop_round` 重置为 1，而旧实现只在 `loop_round > 1` 时承认当前 Run 的前序 Attempt，随后错误回退到 `parent_run_id`。

## 决策与实现

- 同一节点只要在当前 Run 已存在前序 `attempt.created`，新 Attempt 就以该事件的实际 `run_id` 作为 `rework_of_run_id`，不再依赖会跨 epoch 重置的 `loop_round`。
- 新 Attempt 的 `rework_of` 同时引用前序事件中的稳定 `platform_attempt_id`，避免出现只有 Run 指针却没有具体 Attempt 指针的半条血缘。
- 有前序 Attempt 时，`supersedes` 继续引用该节点最近 Artifact；没有前序 Attempt 的真正跨 Run 首次重试仍保留父 Run 关系。
- 当前 epoch 31 的既有不可变事件不被修改或覆盖；修复只作用于后续安全边界加载后的新 Attempt。

## 验证

```text
python -m compileall -q server/app/platform_executor.py
PASS

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest -p anyio.pytest_plugin server/tests/runtime_contract/test_runtime_execution_safety.py -q
34 passed, 1 third-party warning
```

新增合同覆盖 `loop_round=1` 但存在同 Run 前序 Attempt 的恢复场景，并验证能够提取具体 `platform_attempt_id`。第一次直接运行 pytest 时，本机全局 `logfire/opentelemetry` 插件发生导入冲突；显式禁用无关插件、只加载项目所需 AnyIO 插件后，完整测试文件通过。

## 运行期处理

记录本文件时，唯一验收 Run 仍为 `running / 80%`，`final_report_and_gap_list` 正在由五角色 Claude Code SDK Bridge 执行，事件至少增长到 sequence `65353`。为避免破坏真实长任务，当前后端不热重启；待角色完成、暂停、失败或 Judge 退回形成安全边界后，再加载本修复并从同一 Run、Version 定向继续。
